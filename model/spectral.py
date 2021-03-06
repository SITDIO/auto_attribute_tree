# -*- coding: utf-8 -*-
# Based on implementations by:
#         Gael Varoquaux gael.varoquaux@normalesup.org
#         Brian Cheung
#         Wei LI <kuantkid@gmail.com>"""
import warnings

import numpy as np

from sklearn.base import BaseEstimator, ClusterMixin
from sklearn.utils import check_random_state, as_float_array
from sklearn.utils.validation import _deprecate_positional_args
from sklearn.utils.deprecation import deprecated
from sklearn.metrics.pairwise import pairwise_kernels
from sklearn.neighbors import kneighbors_graph, NearestNeighbors
from sklearn.manifold import spectral_embedding
from sklearn.cluster._kmeans import k_means
from sklearn_extra.cluster import KMedoids


@_deprecate_positional_args
def discretize(vectors, *, copy=True, max_svd_restarts=30, n_iter_max=20,
               random_state=None):
    """Search for a partition matrix (clustering) which is closest to the
    eigenvector embedding.
    Parameters
    ----------
    vectors : array-like of shape (n_samples, n_clusters)
        The embedding space of the samples.
    copy : bool, default=True
        Whether to copy vectors, or perform in-place normalization.
    max_svd_restarts : int, default=30
        Maximum number of attempts to restart SVD if convergence fails
    n_iter_max : int, default=30
        Maximum number of iterations to attempt in rotation and partition
        matrix search if machine precision convergence is not reached
    random_state : int, RandomState instance, default=None
        Determines random number generation for rotation matrix initialization.
        Use an int to make the randomness deterministic.
        See :term:`Glossary <random_state>`.
    Returns
    -------
    labels : array of integers, shape: n_samples
        The labels of the clusters.
    References
    ----------
    - Multiclass spectral clustering, 2003
      Stella X. Yu, Jianbo Shi
      https://www1.icsi.berkeley.edu/~stellayu/publication/doc/2003kwayICCV.pdf
    Notes
    -----
    The eigenvector embedding is used to iteratively search for the
    closest discrete partition.  First, the eigenvector embedding is
    normalized to the space of partition matrices. An optimal discrete
    partition matrix closest to this normalized embedding multiplied by
    an initial rotation is calculated.  Fixing this discrete partition
    matrix, an optimal rotation matrix is calculated.  These two
    calculations are performed until convergence.  The discrete partition
    matrix is returned as the clustering solution.  Used in spectral
    clustering, this method tends to be faster and more robust to random
    initialization than k-means.
    """

    from scipy.sparse import csc_matrix
    from scipy.linalg import LinAlgError

    random_state = check_random_state(random_state)

    vectors = as_float_array(vectors, copy=copy)

    eps = np.finfo(float).eps
    n_samples, n_components = vectors.shape

    # Normalize the eigenvectors to an equal length of a vector of ones.
    # Reorient the eigenvectors to point in the negative direction with respect
    # to the first element.  This may have to do with constraining the
    # eigenvectors to lie in a specific quadrant to make the discretization
    # search easier.
    norm_ones = np.sqrt(n_samples)
    for i in range(vectors.shape[1]):
        vectors[:, i] = (vectors[:, i] / np.linalg.norm(vectors[:, i])) \
            * norm_ones
        if vectors[0, i] != 0:
            vectors[:, i] = -1 * vectors[:, i] * np.sign(vectors[0, i])

    # Normalize the rows of the eigenvectors.  Samples should lie on the unit
    # hypersphere centered at the origin.  This transforms the samples in the
    # embedding space to the space of partition matrices.
    vectors = vectors / np.sqrt((vectors ** 2).sum(axis=1))[:, np.newaxis]

    svd_restarts = 0
    has_converged = False

    # If there is an exception we try to randomize and rerun SVD again
    # do this max_svd_restarts times.
    while (svd_restarts < max_svd_restarts) and not has_converged:

        # Initialize first column of rotation matrix with a row of the
        # eigenvectors
        rotation = np.zeros((n_components, n_components))
        rotation[:, 0] = vectors[random_state.randint(n_samples), :].T

        # To initialize the rest of the rotation matrix, find the rows
        # of the eigenvectors that are as orthogonal to each other as
        # possible
        c = np.zeros(n_samples)
        for j in range(1, n_components):
            # Accumulate c to ensure row is as orthogonal as possible to
            # previous picks as well as current one
            c += np.abs(np.dot(vectors, rotation[:, j - 1]))
            rotation[:, j] = vectors[c.argmin(), :].T

        last_objective_value = 0.0
        n_iter = 0

        while not has_converged:
            n_iter += 1

            t_discrete = np.dot(vectors, rotation)

            labels = t_discrete.argmax(axis=1)
            vectors_discrete = csc_matrix(
                (np.ones(len(labels)), (np.arange(0, n_samples), labels)),
                shape=(n_samples, n_components))

            t_svd = vectors_discrete.T * vectors

            try:
                U, S, Vh = np.linalg.svd(t_svd)
                svd_restarts += 1
            except LinAlgError:
                print("SVD did not converge, randomizing and trying again")
                break

            ncut_value = 2.0 * (n_samples - S.sum())
            if ((abs(ncut_value - last_objective_value) < eps) or
                    (n_iter > n_iter_max)):
                has_converged = True
            else:
                # otherwise calculate rotation and continue
                last_objective_value = ncut_value
                rotation = np.dot(Vh.T, U.T)

    if not has_converged:
        raise LinAlgError('SVD did not converge')
    return labels


@_deprecate_positional_args
def spectral_clustering_mod(affinity, *, n_clusters=8, n_components=None,
                            eigen_solver=None, random_state=None, n_init=10,
                            eigen_tol=0.0, assign_labels='kmeans',
                            verbose=False):
    """Modified implementation of sklearn's spectral clustering
    Apply clustering to a projection of the normalized Laplacian.
    In practice Spectral Clustering is very useful when the structure of
    the individual clusters is highly non-convex or more generally when
    a measure of the center and spread of the cluster is not a suitable
    description of the complete cluster. For instance, when clusters are
    nested circles on the 2D plane.
    If affinity is the adjacency matrix of a graph, this method can be
    used to find normalized graph cuts.
    Read more in the :ref:`User Guide <spectral_clustering>`.
    Parameters
    ----------
    affinity : {array-like, sparse matrix} of shape (n_samples, n_samples)
        The affinity matrix describing the relationship of the samples to
        embed. **Must be symmetric**.
        Possible examples:
          - adjacency matrix of a graph,
          - heat kernel of the pairwise distance matrix of the samples,
          - symmetric k-nearest neighbours connectivity matrix of the samples.
    n_clusters : int, default=None
        Number of clusters to extract.
    n_components : int, default=n_clusters
        Number of eigenvectors to use for the spectral embedding
    eigen_solver : {None, 'arpack', 'lobpcg', or 'amg'}
        The eigenvalue decomposition strategy to use. AMG requires pyamg
        to be installed. It can be faster on very large, sparse problems,
        but may also lead to instabilities. If None, then ``'arpack'`` is
        used.
    random_state : int, RandomState instance, default=None
        A pseudo random number generator used for the initialization of the
        lobpcg eigenvectors decomposition when eigen_solver == 'amg' and by
        the K-Means initialization. Use an int to make the randomness
        deterministic.
        See :term:`Glossary <random_state>`.
    n_init : int, default=10
        Number of time the k-means algorithm will be run with different
        centroid seeds. The final results will be the best output of n_init
        consecutive runs in terms of inertia. Only used if
        ``assign_labels='kmeans'``.
    eigen_tol : float, default=0.0
        Stopping criterion for eigendecomposition of the Laplacian matrix
        when using arpack eigen_solver.
    assign_labels : {'kmedoids', 'kmeans', 'discretize'}, default='kmedoids'
        The strategy to use to assign labels in the embedding
        space.  There are two ways to assign labels after the Laplacian
        embedding.  k-means can be applied and is a popular choice. But it can
        also be sensitive to initialization. Discretization is another
        approach which is less sensitive to random initialization. See
        the 'Multiclass spectral clustering' paper referenced below for
        more details on the discretization approach.
    verbose : bool, default=False
        Verbosity mode.
        .. versionadded:: 0.24
    Returns
    -------
    labels : array of integers, shape: n_samples
        The labels of the clusters.
    References
    ----------
    - Normalized cuts and image segmentation, 2000
      Jianbo Shi, Jitendra Malik
      http://citeseer.ist.psu.edu/viewdoc/summary?doi=10.1.1.160.2324
    - A Tutorial on Spectral Clustering, 2007
      Ulrike von Luxburg
      http://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.165.9323
    - Multiclass spectral clustering, 2003
      Stella X. Yu, Jianbo Shi
      https://www1.icsi.berkeley.edu/~stellayu/publication/doc/2003kwayICCV.pdf
    Notes
    -----
    The graph should contain only one connect component, elsewhere
    the results make little sense.
    This algorithm solves the normalized cut for k=2: it is a
    normalized spectral clustering.
    """
    if assign_labels not in ('kmedoids', 'kmeans', 'discretize'):
        raise ValueError("The 'assign_labels' parameter should be "
                         "'kmedoids', 'kmeans' or 'discretize', but '%s' was given"
                         % assign_labels)

    random_state = check_random_state(random_state)
    n_components = n_clusters if n_components is None else n_components

    # The first eigenvector is constant only for fully connected graphs
    # and should be kept for spectral clustering (drop_first = False)
    # See spectral_embedding documentation.
    maps = spectral_embedding(affinity, n_components=n_components,
                              eigen_solver=eigen_solver,
                              random_state=random_state,
                              eigen_tol=eigen_tol, drop_first=False)
    if verbose:
        print(f'Computing label assignment using {assign_labels}')

    if assign_labels == 'kmedoids':
        cluster_centers, labels, _ = k_medoids(maps, n_clusters, random_state=random_state,
                                               n_init=n_init, verbose=verbose)
    elif assign_labels == 'kmeans':
        cluster_centers, labels, _ = k_means(maps, n_clusters, random_state=random_state,
                                             n_init=n_init, verbose=verbose)
    else:
        cluster_centers, labels = None, discretize(
            maps, random_state=random_state)

    return labels, maps, cluster_centers


class SpectralClustering(ClusterMixin, BaseEstimator):
    """Apply clustering to a projection of the normalized Laplacian.
    In practice Spectral Clustering is very useful when the structure of
    the individual clusters is highly non-convex, or more generally when
    a measure of the center and spread of the cluster is not a suitable
    description of the complete cluster, such as when clusters are
    nested circles on the 2D plane.
    If the affinity matrix is the adjacency matrix of a graph, this method
    can be used to find normalized graph cuts.
    When calling ``fit``, an affinity matrix is constructed using either
    a kernel function such the Gaussian (aka RBF) kernel with Euclidean
    distance ``d(X, X)``::
            np.exp(-gamma * d(X,X) ** 2)
    or a k-nearest neighbors connectivity matrix.
    Alternatively, a user-provided affinity matrix can be specified by
    setting ``affinity='precomputed'``.
    Read more in the :ref:`User Guide <spectral_clustering>`.
    Parameters
    ----------
    n_clusters : int, default=8
        The dimension of the projection subspace.
    eigen_solver : {'arpack', 'lobpcg', 'amg'}, default=None
        The eigenvalue decomposition strategy to use. AMG requires pyamg
        to be installed. It can be faster on very large, sparse problems,
        but may also lead to instabilities. If None, then ``'arpack'`` is
        used.
    n_components : int, default=n_clusters
        Number of eigenvectors to use for the spectral embedding
    random_state : int, RandomState instance, default=None
        A pseudo random number generator used for the initialization of the
        lobpcg eigenvectors decomposition when ``eigen_solver='amg'`` and by
        the K-Means initialization. Use an int to make the randomness
        deterministic.
        See :term:`Glossary <random_state>`.
    n_init : int, default=10
        Number of time the k-means algorithm will be run with different
        centroid seeds. The final results will be the best output of n_init
        consecutive runs in terms of inertia. Only used if
        ``assign_labels='kmeans'``.
    gamma : float, default=1.0
        Kernel coefficient for rbf, poly, sigmoid, laplacian and chi2 kernels.
        Ignored for ``affinity='nearest_neighbors'``.
    affinity : str or callable, default='rbf'
        How to construct the affinity matrix.
         - 'nearest_neighbors': construct the affinity matrix by computing a
           graph of nearest neighbors.
         - 'rbf': construct the affinity matrix using a radial basis function
           (RBF) kernel.
         - 'precomputed': interpret ``X`` as a precomputed affinity matrix,
           where larger values indicate greater similarity between instances.
         - 'precomputed_nearest_neighbors': interpret ``X`` as a sparse graph
           of precomputed distances, and construct a binary affinity matrix
           from the ``n_neighbors`` nearest neighbors of each instance.
         - one of the kernels supported by
           :func:`~sklearn.metrics.pairwise_kernels`.
        Only kernels that produce similarity scores (non-negative values that
        increase with similarity) should be used. This property is not checked
        by the clustering algorithm.
    n_neighbors : int, default=10
        Number of neighbors to use when constructing the affinity matrix using
        the nearest neighbors method. Ignored for ``affinity='rbf'``.
    eigen_tol : float, default=0.0
        Stopping criterion for eigendecomposition of the Laplacian matrix
        when ``eigen_solver='arpack'``.
    assign_labels : {'kmeans', 'discretize'}, default='kmeans'
        The strategy for assigning labels in the embedding space. There are two
        ways to assign labels after the Laplacian embedding. k-means is a
        popular choice, but it can be sensitive to initialization.
        Discretization is another approach which is less sensitive to random
        initialization.
    degree : float, default=3
        Degree of the polynomial kernel. Ignored by other kernels.
    coef0 : float, default=1
        Zero coefficient for polynomial and sigmoid kernels.
        Ignored by other kernels.
    kernel_params : dict of str to any, default=None
        Parameters (keyword arguments) and values for kernel passed as
        callable object. Ignored by other kernels.
    n_jobs : int, default=None
        The number of parallel jobs to run when `affinity='nearest_neighbors'`
        or `affinity='precomputed_nearest_neighbors'`. The neighbors search
        will be done in parallel.
        ``None`` means 1 unless in a :obj:`joblib.parallel_backend` context.
        ``-1`` means using all processors. See :term:`Glossary <n_jobs>`
        for more details.
    verbose : bool, default=False
        Verbosity mode.
        .. versionadded:: 0.24
    Attributes
    ----------
    affinity_matrix_ : array-like of shape (n_samples, n_samples)
        Affinity matrix used for clustering. Available only after calling
        ``fit``.
    labels_ : ndarray of shape (n_samples,)
        Labels of each point
    Examples
    --------
    >>> from sklearn.cluster import SpectralClustering
    >>> import numpy as np
    >>> X = np.array([[1, 1], [2, 1], [1, 0],
    ...               [4, 7], [3, 5], [3, 6]])
    >>> clustering = SpectralClustering(n_clusters=2,
    ...         assign_labels='discretize',
    ...         random_state=0).fit(X)
    >>> clustering.labels_
    array([1, 1, 1, 0, 0, 0])
    >>> clustering
    SpectralClustering(assign_labels='discretize', n_clusters=2,
        random_state=0)
    Notes
    -----
    A distance matrix for which 0 indicates identical elements and high values
    indicate very dissimilar elements can be transformed into an affinity /
    similarity matrix that is well-suited for the algorithm by
    applying the Gaussian (aka RBF, heat) kernel::
        np.exp(- dist_matrix ** 2 / (2. * delta ** 2))
    where ``delta`` is a free parameter representing the width of the Gaussian
    kernel.
    An alternative is to take a symmetric version of the k-nearest neighbors
    connectivity matrix of the points.
    If the pyamg package is installed, it is used: this greatly
    speeds up computation.
    References
    ----------
    - Normalized cuts and image segmentation, 2000
      Jianbo Shi, Jitendra Malik
      http://citeseer.ist.psu.edu/viewdoc/summary?doi=10.1.1.160.2324
    - A Tutorial on Spectral Clustering, 2007
      Ulrike von Luxburg
      http://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.165.9323
    - Multiclass spectral clustering, 2003
      Stella X. Yu, Jianbo Shi
      https://www1.icsi.berkeley.edu/~stellayu/publication/doc/2003kwayICCV.pdf
    """
    @_deprecate_positional_args
    def __init__(self, n_clusters=8, *, eigen_solver=None, n_components=None,
                 random_state=None, n_init=10, gamma=1., affinity='rbf',
                 n_neighbors=10, eigen_tol=0.0, assign_labels='kmeans',
                 degree=3, coef0=1, kernel_params=None, n_jobs=None,
                 verbose=False):
        self.n_clusters = n_clusters
        self.eigen_solver = eigen_solver
        self.n_components = n_components
        self.random_state = random_state
        self.n_init = n_init
        self.gamma = gamma
        self.affinity = affinity
        self.n_neighbors = n_neighbors
        self.eigen_tol = eigen_tol
        self.assign_labels = assign_labels
        self.degree = degree
        self.coef0 = coef0
        self.kernel_params = kernel_params
        self.n_jobs = n_jobs
        self.verbose = verbose

    def fit(self, X, y=None):
        """Perform spectral clustering from features, or affinity matrix.
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features) or \
                (n_samples, n_samples)
            Training instances to cluster, similarities / affinities between
            instances if ``affinity='precomputed'``, or distances between
            instances if ``affinity='precomputed_nearest_neighbors``. If a
            sparse matrix is provided in a format other than ``csr_matrix``,
            ``csc_matrix``, or ``coo_matrix``, it will be converted into a
            sparse ``csr_matrix``.
        y : Ignored
            Not used, present here for API consistency by convention.
        Returns
        -------
        self
        """
        X = self._validate_data(X, accept_sparse=['csr', 'csc', 'coo'],
                                dtype=np.float64, ensure_min_samples=2)
        allow_squared = self.affinity in ["precomputed",
                                          "precomputed_nearest_neighbors"]
        if X.shape[0] == X.shape[1] and not allow_squared:
            warnings.warn("The spectral clustering API has changed. ``fit``"
                          "now constructs an affinity matrix from data. To use"
                          " a custom affinity matrix, "
                          "set ``affinity=precomputed``.")

        if self.affinity == 'nearest_neighbors':
            connectivity = kneighbors_graph(X, n_neighbors=self.n_neighbors,
                                            include_self=True,
                                            n_jobs=self.n_jobs)
            self.affinity_matrix_ = 0.5 * (connectivity + connectivity.T)
        elif self.affinity == 'precomputed_nearest_neighbors':
            estimator = NearestNeighbors(n_neighbors=self.n_neighbors,
                                         n_jobs=self.n_jobs,
                                         metric="precomputed").fit(X)
            connectivity = estimator.kneighbors_graph(X=X, mode='connectivity')
            self.affinity_matrix_ = 0.5 * (connectivity + connectivity.T)
        elif self.affinity == 'precomputed':
            self.affinity_matrix_ = X
        else:
            params = self.kernel_params
            if params is None:
                params = {}
            if not callable(self.affinity):
                params['gamma'] = self.gamma
                params['degree'] = self.degree
                params['coef0'] = self.coef0
            self.affinity_matrix_ = pairwise_kernels(X, metric=self.affinity,
                                                     filter_params=True,
                                                     **params)

        random_state = check_random_state(self.random_state)
        self.labels_, \
            self.maps_, \
            self.medoid_indices_ = spectral_clustering_mod(self.affinity_matrix_,
                                                           n_clusters=self.n_clusters,
                                                           n_components=self.n_components,
                                                           eigen_solver=self.eigen_solver,
                                                           random_state=random_state,
                                                           n_init=self.n_init,
                                                           eigen_tol=self.eigen_tol,
                                                           assign_labels=self.assign_labels,
                                                           verbose=self.verbose)
        return self

    def fit_predict(self, X, y=None):
        """Perform spectral clustering from features, or affinity matrix,
        and return cluster labels.
        Parameters
        ----------
        X : {array-like, sparse matrix} of shape (n_samples, n_features) or \
                (n_samples, n_samples)
            Training instances to cluster, similarities / affinities between
            instances if ``affinity='precomputed'``, or distances between
            instances if ``affinity='precomputed_nearest_neighbors``. If a
            sparse matrix is provided in a format other than ``csr_matrix``,
            ``csc_matrix``, or ``coo_matrix``, it will be converted into a
            sparse ``csr_matrix``.
        y : Ignored
            Not used, present here for API consistency by convention.
        Returns
        -------
        labels : ndarray of shape (n_samples,)
            Cluster labels.
        """
        return super().fit_predict(X, y)

    def _more_tags(self):
        return {'pairwise': self.affinity in ["precomputed",
                                              "precomputed_nearest_neighbors"]}

    # TODO: Remove in 1.1
    # mypy error: Decorated property not supported
    @deprecated("Attribute _pairwise was deprecated in "  # type: ignore
                "version 0.24 and will be removed in 1.1 (renaming of 0.26).")
    @property
    def _pairwise(self):
        return self.affinity in ["precomputed",
                                 "precomputed_nearest_neighbors"]


@_deprecate_positional_args
def k_medoids(X, n_clusters, *, init='k-medoids++', max_iter=300,
              random_state=None, algorithm="pam", return_n_iter=False, **kwargs):
    """TODO K-means clustering algorithm.
    Read more in the :ref:`User Guide <k_means>`.
    Parameters
    ----------
    X : {array-like, sparse matrix} of shape (n_samples, n_features)
        The observations to cluster. It must be noted that the data
        will be converted to C ordering, which will cause a memory copy
        if the given data is not C-contiguous.
    n_clusters : int
        The number of clusters to form as well as the number of
        centroids to generate.
    TODO init : {'k-medoids++', 'random'}, callable or array-like of shape \
            (n_clusters, n_features), default='k-means++'
        Method for initialization:
        'k-means++' : selects initial cluster centers for k-mean
        clustering in a smart way to speed up convergence. See section
        Notes in k_init for more details.
        'random': choose `n_clusters` observations (rows) at random from data
        for the initial centroids.
        If an array is passed, it should be of shape (n_clusters, n_features)
        and gives the initial centers.
        If a callable is passed, it should take arguments X, n_clusters and a
        random state and return an initialization.
    max_iter : int, default=300
        Maximum number of iterations of the k-means algorithm to run.
    random_state : int, RandomState instance or None, default=None
        Determines random number generation for centroid initialization. Use
        an int to make the randomness deterministic.
        See :term:`Glossary <random_state>`.
    TODO algorithm : {"auto", "full", "elkan"}, default="auto"
        K-means algorithm to use. The classical EM-style algorithm is "full".
        The "elkan" variation is more efficient on data with well-defined
        clusters, by using the triangle inequality. However it's more memory
        intensive due to the allocation of an extra array of shape
        (n_samples, n_clusters).
        For now "auto" (kept for backward compatibility) chooses "elkan" but it
        might change in the future for a better heuristic.
    return_n_iter : bool, default=False
        Whether or not to return the number of iterations.
    Returns
    -------
    TODO
    centroid : ndarray of shape (n_clusters, n_features)
        Centroids found at the last iteration of k-means.
    label : ndarray of shape (n_samples,)
        label[i] is the code or index of the centroid the
        i'th observation is closest to.
    inertia : float
        The final value of the inertia criterion (sum of squared distances to
        the closest centroid for all observations in the training set).
    best_n_iter : int
        Number of iterations corresponding to the best results.
        Returned only if `return_n_iter` is set to True.
    """
    est = KMedoids(
        n_clusters=n_clusters, init=init, max_iter=max_iter,
        random_state=random_state, method=algorithm
    ).fit(X)

    if return_n_iter:
        return est.medoid_indices_, est.labels_, est.inertia_, est.n_iter_
    else:
        return est.medoid_indices_, est.labels_, est.inertia_
