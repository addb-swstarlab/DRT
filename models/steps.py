
from models.cluster import GapStatistic, KMeansClusters, create_kselection_model
from models.factor_analysis import FactorAnalysis
from models.preprocessing import (get_shuffle_indices, consolidate_columnlabels)
from models.mean_shift import MeanShiftClustering

from models.ranking import Ranking

from models.gp import GPRNP

from sklearn.preprocessing import StandardScaler
from sklearn.gaussian_process import GaussianProcessRegressor
import numpy as np
from models.parameters import *

import utils

#Step 1
def metricSimplification(metric_data, logger):
    matrix = metric_data['data']
    columnlabels = metric_data['columnlabels']

    # # Bin each column (metric) in the matrix by its decile
    # binner = Bin(bin_start=1, axis=0)
    # binned_matrix = binner.fit_transform(matrix)

    # Remove any constant columns
    nonconst_matrix = []
    nonconst_columnlabels = []
    for col, (_,v) in zip(matrix.T, enumerate(columnlabels)):
        if np.any(col != col[0]):
            #print(col.reshape(-1, 1))
            nonconst_matrix.append(col.reshape(-1, 1))
            nonconst_columnlabels.append(v)
    assert len(nonconst_matrix) > 0, "Need more data to train the model"
    nonconst_matrix = np.hstack(nonconst_matrix)
    logger.info("Workload characterization ~ nonconst data size: %s", nonconst_matrix.shape)

    # Remove any duplicate columns
    unique_matrix, unique_idxs = np.unique(nonconst_matrix, axis=1, return_index=True)
    unique_columnlabels = [nonconst_columnlabels[idx] for idx in unique_idxs]

    logger.info("Workload characterization ~ final data size: %s", unique_matrix.shape)
    n_rows, n_cols = unique_matrix.shape

    # Shuffle the matrix rows
    shuffle_indices = get_shuffle_indices(n_rows)
    shuffled_matrix = unique_matrix[shuffle_indices, :]

    #FactorAnalysis
    fa_model = FactorAnalysis()
    fa_model.fit(shuffled_matrix, unique_columnlabels, n_components=5)
    # Components: metrics * factors
    components = fa_model.components_.T.copy()


    # #KMeansClusters()
    kmeans_models = KMeansClusters()
    ##TODO: Check Those Options
    kmeans_models.fit(components, min_cluster=1,
                      max_cluster=min(n_cols - 1, 20),
                      sample_labels=unique_columnlabels,
                      estimator_params={'n_init': 100})

    # print(components)
    # model = MeanShiftClustering(components)
    # clusters = model.fit(components)
    # print("cluster_centers_",model.model.cluster_centers_)
    # print("cluster_labels_",model.model.labels_)
    # print(clusters)
    # for i in np.unique(clusters):
    #     print(unique_columnlabels[list(clusters).index(i)])

    # from sklearn.mixture import GaussianMixture
    # gmm = GaussianMixture(n_components=2,random_state=0).fit(components)
    # #print(gmm.means_)
    # gmm_cluster_labels = gmm.predict(components)
    # gmm_cluster ={}
    # for i,labels in enumerate(gmm_cluster_labels):
    #     if gmm_cluster.get(labels):
    #         gmm_cluster[labels].append(unique_columnlabels[i])
    #     else:
    #         gmm_cluster[labels] = [unique_columnlabels[i]]
    # print(gmm_cluster)

    # Compute optimal # clusters, k, using gap statistics
    gapk = create_kselection_model("gap-statistic")
    gapk.fit(components, kmeans_models.cluster_map_)

    logger.info("Found optimal number of clusters: {}".format(gapk.optimal_num_clusters_))

    # Get pruned metrics, cloest samples of each cluster center
    pruned_metrics = kmeans_models.cluster_map_[gapk.optimal_num_clusters_].get_closest_samples()

    return pruned_metrics


def knobsRanking(knob_data, metric_data, mode, logger):
    """
    knob_data : will be ranked by knobs_ranking
    metric_data : pruned metric_data by metric simplification
    mode : selct knob_identification(like lasso, xgb, rf)
    logger
    """
    knob_matrix = knob_data['data']
    knob_columnlabels = knob_data['columnlabels']

    metric_matrix = metric_data['data']
    #metric_columnlabels = metric_data['columnlabels']

    encoded_knob_columnlabels = knob_columnlabels
    encoded_knob_matrix = knob_matrix

    # standardize values in each column to N(0, 1)
    standardizer = StandardScaler()
    standardized_knob_matrix = standardizer.fit_transform(encoded_knob_matrix)
    standardized_metric_matrix = standardizer.fit_transform(metric_matrix)

    # shuffle rows (note: same shuffle applied to both knob and metric matrices)
    shuffle_indices = get_shuffle_indices(standardized_knob_matrix.shape[0], seed=17)
    shuffled_knob_matrix = standardized_knob_matrix[shuffle_indices, :]
    shuffled_metric_matrix = standardized_metric_matrix[shuffle_indices, :]

    model = Ranking(mode)
    model.fit(shuffled_knob_matrix,shuffled_metric_matrix,encoded_knob_columnlabels)
    encoded_knobs = model.get_ranked_features()
    feature_imp = model.get_ranked_importance()
    if feature_imp is None:
        pass
    else:
        logger.info('Feature importance')
        logger.info(feature_imp)

    consolidated_knobs = consolidate_columnlabels(encoded_knobs)

    return consolidated_knobs

def memtier_parsing(*args):
    pass


def configuration_recommendation(target_knob, target_metric, logger, gp_type='numpy', db_type='redis', data_type='RDB'):
    X_columnlabels, X_scaler, X_scaled, y_scaled, X_max, X_min, _ = utils.process_training_data(target_knob, target_metric, db_type, data_type)

    num_samples = params["NUM_SAMPLES"]
    X_samples = np.empty((num_samples, X_scaled.shape[1]))
    for i in range(X_scaled.shape[1]):
        X_samples[:, i] = np.random.rand(num_samples) * (X_max[i] - X_min[i]) + X_min[i]

    # q = queue.PriorityQueue()
    # for x in range(0, y_scaled.shape[0]):
    #     q.put((y_scaled[x][0], x))

    # ## TODO : What...?
    # i = 0
    # while i < params['TOP_NUM_CONFIG']:
    #     try:
    #         item = q.get_nowait()
    #         # Tensorflow get broken if we use the training data points as
    #         # starting points for GPRGD. We add a small bias for the
    #         # starting points. GPR_EPS default value is 0.001
    #         # if the starting point is X_max, we minus a small bias to
    #         # make sure it is within the range.
    #         dist = sum(np.square(X_max - X_scaled[item[1]]))
    #         if dist < 0.001:
    #             X_samples = np.vstack((X_samples, X_scaled[item[1]] - abs(params['GPR_EPS'])))
    #         else:
    #             X_samples = np.vstack((X_samples, X_scaled[item[1]] + abs(params['GPR_EPS'])))
    #         i = i + 1
    #     except queue.Empty:
    #         break
    res = None
    if gp_type == 'numpy':
        # DO GPRNP
        model = GPRNP(length_scale = params["GPR_LENGTH_SCALE"],
                        magnitude=params["GPR_MAGNITUDE"],
                        max_train_size=params['GPR_MAX_TRAIN_SIZE'],
                        batch_size=params['GPR_BATCH_SIZE'])
        model.fit(X_scaled,y_scaled,ridge=params["GPR_RIDGE"])
        res = model.predict(X_samples).ypreds
        logger.info('do GPRNP')
        del model
    elif gp_type == 'scikit':
        # # DO SCIKIT-LEARN GP
        # model = GaussianProcessRegressor().fit(X_scaled,y_scaled)
        # res = model.predict(X_samples)
        # print('do scikit-learn gp')

        from sklearn.gaussian_process.kernels import DotProduct
        GPRkernel = DotProduct(sigma_0=0.5)
        model = GaussianProcessRegressor(kernel = GPRkernel,
                            alpha = params["ALPHA"]).fit(X_scaled,y_scaled)
        res = model.predict(X_samples)
        del model
    else:
        raise Exception("gp_type should be one of (numpy and scikit)")

    best_config_idx = np.argmax(res.ravel())
    if len(set(res.ravel()))==1:
        logger.info("FAIL TRAIN")
        return False, -float('inf'), None
    best_config = X_samples[best_config_idx, :]
    best_config = X_scaler.inverse_transform(best_config)
    X_min_inv = X_scaler.inverse_transform(X_min)
    X_max_inv = X_scaler.inverse_transform(X_max)
    best_config = np.minimum(best_config, X_max_inv)
    best_config = np.maximum(best_config, X_min_inv)
    conf_map = {k: best_config[i] for i, k in enumerate(X_columnlabels)}
    # logger.info("\n\n\n")
    logger.info(conf_map)
    #convert_dict_to_conf(conf_map, data_type)

    logger.info("FINISH TRAIN")
    print(np.max(res.ravel()))
    return True, np.max(res.ravel()), conf_map