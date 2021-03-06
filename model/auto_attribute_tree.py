# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
from collections import defaultdict
from sklearn import preprocessing
from .pamk import pamk


def level_pamk(data, max_k=10, offset=0, alpha=1e-3, method='pam', random_state=None):
    id_col = data.iloc[:, 0]
    X = data.iloc[:, 1:].values
    max_k = min(len(data)-1, max_k)
    pam_res = pamk(X, krange=np.arange(1, max_k+1), method=method, n_components=10,
                   alpha=alpha, random_state=random_state)

    if pam_res[1] != 1:
        medoids = id_col.iloc[pam_res[0].medoid_indices_]
        medoids = pd.DataFrame(
            {'cluster': np.arange(offset + 1, offset + 1 + pam_res[1]), 'id': medoids})
        clusters = pd.DataFrame(
            {'id': id_col, 'cluster': pam_res[0].labels_ + offset + 1})
    else:
        medoids = pd.DataFrame()
        clusters = pd.DataFrame()

    return clusters, medoids


class Node():
    def __init__(self, name, parent_node, data=None):
        self.name = name
        self.parent_node = parent_node
        self.children_nodes = []
        self.data = data

    def __repr__(self):
        return f'Node_{self.name}'

    def add_child(self, child_node) -> None:
        self.children_nodes.append(child_node)

    def remove_child(self, child_node) -> None:
        self.children_nodes.remove(child_node)

    def del_data(self) -> None:
        self.data = None


class AutoAttributeTree():
    def __init__(self, max_k=10, method='spectral_pam', random_state=None):
        self.nodes = []
        self.incomplete_nodes = [0]
        self.medoids = pd.DataFrame()
        self.levels2nodes = defaultdict(list)
        self.nodes2levels = {}
        self.max_k = max_k
        self.leaf_nodes_idx = []
        self.standard_scaler = preprocessing.StandardScaler()
        self.method = method
        self.random_state = random_state

    def fit(self, data):
        scaled_data = data.copy()
        scaled_data.iloc[:, 1:] = self.z_score(scaled_data.iloc[:, 1:])
        level = 0
        data_node = scaled_data
        self.nodes.append(Node(0, None, data_node))
        self.levels2nodes[level].append(0)
        self.nodes2levels[0] = level
        while len(self.incomplete_nodes) > 0:
            current_node_idx = self.incomplete_nodes.pop(0)
            current_node = self.nodes[current_node_idx]
            if current_node_idx > 0:
                data_node = current_node.data
                level = self.nodes2levels[current_node_idx]
            if len(data_node) > 2:
                clustered_data, medoids = level_pamk(
                    data_node, max_k=self.max_k, offset=len(self.nodes)-1,
                    method=self.method, random_state=self.random_state)
            else:
                print(
                    f'Node {current_node} did not divided because of too few data')
                continue
            if len(medoids) > 1:
                self.medoids = self.medoids.append(medoids)
                self.incomplete_nodes += list(medoids.cluster)
                for n in list(medoids.cluster):
                    current_node.add_child(n)
                    mask = [i in list(clustered_data.id[clustered_data.cluster == n])
                            for i in data_node.iloc[:, 0]]
                    self.nodes.append(
                        Node(n, current_node_idx, data_node[mask]))
                    self.levels2nodes[level+1].append(n)
                    self.nodes2levels[n] = level+1
                current_node.del_data()
            else:
                print(
                    f'Node {current_node} did not divided again according to Duda-Hart test')

        self.leaf_nodes_idx = [
            n.name for n in self.nodes if n.data is not None]
        print('Stop criteria reached')

    def get_clusters(self, level=None):
        clustered_data = pd.DataFrame()
        if level is None:
            level = max(self.levels2nodes.keys())
        for n_idx in self.leaf_nodes_idx:
            node = self.nodes[n_idx]
            data_node = node.data.iloc[:, [0]].copy()
            while self.nodes2levels[n_idx] > level:
                n_idx = node.parent_node
                node = self.nodes[n_idx]
            data_node.loc[:, 'cluster'] = n_idx
            clustered_data = clustered_data.append(data_node)

        return clustered_data

    def z_score(self, X):
        X_scaled = self.standard_scaler.fit_transform(X.values)
        X = pd.DataFrame(X_scaled, columns=X.columns)

        return X

    def num_levels(self):
        return max(self.levels2nodes.keys()) + 1
