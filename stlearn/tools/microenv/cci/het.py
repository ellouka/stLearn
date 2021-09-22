import numpy as np
import pandas as pd
from anndata import AnnData
import scipy.spatial as spatial
from numba.typed import List
from numba import njit, jit

def count(
    adata: AnnData,
    use_label: str = None,
    use_het: str = "cci_het",
    verbose: bool = True,
    distance: float = None,
) -> AnnData:
    """Count the cell type densities
    Parameters
    ----------
    adata: AnnData          The data object including the cell types to count
    use_label:         The cell type results to use in counting
    use_het:                The stoarge place for result
    distance: int           Distance to determine the neighbours (default is the nearest neighbour), distance=0 means within spot

    Returns
    -------
    adata: AnnData          With the counts of specified clusters in nearby spots stored as adata.uns['het']
    """

    library_id = list(adata.uns["spatial"].keys())[0]
    # between spot
    if distance != 0:
        # automatically calculate distance if not given, won't overwrite distance=0 which is within-spot
        if not distance:
            # calculate default neighbour distance
            scalefactors = next(iter(adata.uns["spatial"].values()))["scalefactors"]
            distance = (
                scalefactors["spot_diameter_fullres"]
                * scalefactors[
                    "tissue_"
                    + adata.uns["spatial"][library_id]["use_quality"]
                    + "_scalef"
                ]
                * 2
            )

        counts_ct = pd.DataFrame(0, adata.obs_names, ["CT"])

        # get neighbour spots for each spot
        coor = adata.obs[["imagerow", "imagecol"]]
        point_tree = spatial.cKDTree(coor)
        neighbours = []
        for spot in adata.obs_names:
            n_index = point_tree.query_ball_point(
                np.array(
                    [adata.obs["imagerow"].loc[spot], adata.obs["imagecol"].loc[spot]]
                ),
                distance,
            )
            neighbours = [item for item in adata.obs_names[n_index]]
            counts_ct.loc[spot] = (
                (adata.uns[use_label].loc[neighbours] > 0.2).sum() > 0
            ).sum()
        adata.obsm[use_het] = counts_ct["CT"].values

    # within spot
    else:
        # count the cell types with prob > 0.2 in the result of label transfer
        adata.obsm[use_het] = (adata.uns[use_label] > 0.2).sum(axis=1)

    if verbose:
        print(
            "Counts for cluster (cell type) diversity stored into adata.uns['"
            + use_het
            + "']"
        )

    return adata

def get_edges(adata: AnnData, L_bool: np.array, R_bool: np.array,
               sig_bool: np.array):
    """ Gets a list edges representing significant interactions.

    Parameters
    ----------
    adata: AnnData
    L_bool: np.array<bool>  len(L_bool)==len(adata), True if ligand expressed in that spot.
    R_bool: np.array<bool>  len(R_bool)==len(adata), True if receptor expressed in that spot.
    sig_bool np.array<bool>:   len(sig_bool)==len(adata), True if spot has significant LR interactions.
    Returns
    -------
    edge_list_unique:   list<list<str>> Either a list of tuples (directed), or
                        list of sets (undirected), indicating unique significant
                        interactions between spots.
    """
    # Determining the neighbour spots used for significance testing #
    neighbours = List()
    for i in range(adata.uns['spot_neighbours'].shape[0]):
        neighs = np.array(adata.uns['spot_neighbours'].values[i,
                          :][0].split(','))
        neighs = neighs[neighs != ''].astype(int)
        neighbours.append(neighs)

    # Getting the edges to draw in-between #
    L_spot_indices = np.where(np.logical_and(L_bool, sig_bool))[0]
    R_spot_indices = np.where(np.logical_and(R_bool, sig_bool))[0]

    gene_bools = [L_bool, R_bool]
    all_edges = []
    for i, spot_indices in enumerate([L_spot_indices, R_spot_indices]):
        neigh_zip_indices = [(spot_i, neighbours[spot_i]) for spot_i in
                             spot_indices]
        # Getting the barcodes #
        neigh_zip_bcs = [(adata.obs_names[spot_i], adata.obs_names[neigh_indices])
                         for spot_i, neigh_indices in neigh_zip_indices]
        neigh_zip = zip(neigh_zip_bcs, neigh_zip_indices)

        edges = get_between_spot_edge_array(neigh_zip, gene_bools[i],
                                                               undirected=False)
        if i == 1: # Need to reverse the order of the edges #
            edges = [edge[::-1] for edge in edges]
        all_edges.extend( edges )

    # Removing any duplicates #
    all_edges_unique = []
    for edge in all_edges:
        if edge not in all_edges_unique:
            all_edges_unique.append(edge)

    return all_edges_unique

@njit
def get_between_spot_edge_array(neighbourhood_bcs: List,
                                neighbourhood_indices: List,
                                #neigh_zip,
                                neigh_bool: np.array,
                                count_cell_types: bool,
                                cell_data: np.ndarray=None,
                                cutoff: float=0, undirected=True):
    """ undirected=False uses list instead of set to store edges,
    thereby giving direction.
    cell_data is either labels or label transfer scores.
    """
    edge_starts = List()
    edge_ends = List()
    n_edges = 0
    #for bcs, indices in neigh_zip: #bc is cell barcode
    for i in range(len(neighbourhood_bcs)):
        bcs, indices = neighbourhood_bcs[i], neighbourhood_indices[i]
        spot_bc, neigh_bcs = bcs
        neigh_indices = indices[1]
        # Subset the neighbours to only those fitting indicated criteria #
        neigh_bcs = neigh_bcs[neigh_bool[neigh_indices]]
        neigh_indices = neigh_indices[neigh_bool[neigh_indices]]

        if len(neigh_indices) == 0: # No cases where neighbours meet criteria
            continue # Don't add any interactions for this neighbourhood

        # If we have cell data, need to subset neighbours meeting criteria
        if count_cell_types: # User needs to have input cell_data
            # If cutoff specified, then means cell_data refers to cell proportions
            #if mix_mode: # Inputted mixture data, user should have specific cutoff.
            # NOTE is always in mix_mode, for pure cell types just use 0s & 1s #
            interact_bool = cell_data[neigh_indices, :] > cutoff
            interact_neigh_bool = interact_bool.sum(axis=1)
            interact_neigh_bool = interact_neigh_bool == cell_data.shape[1]

        else: # Keep all neighbours with L | R as interacting
            interact_neigh_bool = np.ones((1,neigh_indices.shape[0]))[0,:]==1

        # Retrieving the barcodes of the interacting neighbours #
        interact_neigh_bcs = neigh_bcs[ interact_neigh_bool ]
        for interact_neigh_bc in interact_neigh_bcs:
            edge_starts.append( spot_bc )
            edge_ends.append( interact_neigh_bc )
            n_edges += 1

    # Getting the unique edges #
    edge_added = np.zeros((1,len(edge_starts)))[0,:]==1
    edge_list_unique = List()
    for i in range(n_edges):
        if not edge_added[i]:
            edge_start, edge_end = edge_starts[i], edge_ends[i]
            edge_list_unique.append( (edge_start, edge_end) )
            for j in range(i, n_edges):
                edge_startj, edge_endj = edge_starts[j], edge_ends[j]
                if undirected: # Direction doesn't matter #
                    if (edge_start == edge_startj and edge_end == edge_endj) or \
                       (edge_end == edge_startj and edge_start == edge_endj):
                        edge_added[j] = True
                else:
                    if edge_start == edge_startj and edge_end == edge_endj:
                        edge_added[j] = True

    return edge_list_unique

def count_core(adata: AnnData, use_label: str, neighbours: List,
               spot_indices: np.array = None, neigh_bool: np.array = None,
               label_set=None, spot_mixtures: bool = True, cutoff: float = 0.2,
               return_edges=False,
               ) -> np.array:
    """Get the cell type counts per spot, if spot_mixtures is True & there is \
        per spot deconvolution results available, then counts within spot. \
        If cell type deconvolution results not present but use_label in \
        adata.obs, then counts number of cell types in the neighbourhood.

        Parameters
        ----------
        spot_lr1: np.ndarray          Spots*Ligands
        Returns
        -------
        counts: int   Total number of interactions satisfying the conditions, \
                      or np.array<set> if return_edges=True, where each set is \
                      an edge, only returns unique edges.
    """
    # Ensuring compatibility with current way of adding label_transfer to object
    if use_label == "label_transfer" or use_label == "predictions":
        obs_key, uns_key = "predictions", "label_transfer"
    else:
        obs_key, uns_key = use_label, use_label

    # Just return an empty list if no spot indices #
    if len(spot_indices)==0:
        return [] if return_edges else 0

    # Setting label_set if not present
    if type(label_set) == type(None):
        label_set = np.unique(adata.obs.loc[:,obs_key].values)

    # Setting neigh_bool if not present, is used to filter which spots can be neighbours
    if type(neigh_bool) == type(None):
        neigh_bool = np.array([True]*len(adata))

    # Setting the spot indices to do the counting
    if type(spot_indices) == type(None):
        spot_indices = np.array(list(range(len(adata))))

    # Getting the neighbourhood information #
    neighbourhood_bcs = List()
    neighbourhood_indices = List()
    all_bcs = adata.obs_names.values.astype(str)
    for spot_i in spot_indices:
        neighbourhood_indices.append( (spot_i, neighbours[spot_i]) )
        neighbourhood_bcs.append( (all_bcs[spot_i],
                                   all_bcs[neighbours[spot_i]]) )

    # Getting the barcodes #
    #neigh_zip = zip(neigh_zip_bcs, neigh_zip_indices)

    # Mixture mode
    if spot_mixtures and uns_key in adata.uns:
        # Making sure the label_set in consistent format with columns of adata.uns
        # cols = list(adata.uns[uns_key].columns)
        # col_set = np.array([col for i, col in enumerate(cols)
        #                                                    if col in label_set])

        # within-spot, will have only itself as a neighbour in this mode
        if np.all(np.array([spot_i in neighs for spot_i, neighs
                                                 in neighbourhood_indices])==1):
            # Since each edge link to the spot itself,
            # then need to count the number of significant spots where
            # cellA & cellB > cutoff, & the L/R are expressed.
            ## Getting spots where L/R expressed & cellA > cutoff
            sig_spot_bool = np.array([False]*len(neigh_bool))
            sig_spot_bool[spot_indices] = True
            spots = np.logical_and(sig_spot_bool, neigh_bool)
            ## For the spots where L/R expressed & cellA > cutoff, counting
            ## how many have cellB > cutoff.
            counts = (adata.uns[uns_key].loc[:, label_set].values[spots, :]
                                                           > cutoff).sum(axis=1)
            interact_indices = np.where(counts > 0)[0]
            edge_list = [(adata.obs_names[index]) for index in interact_indices]

        # between-spot
        else:
            # To prevent double counting edges, creating a list of sets,
            # with each set representing an edge, the number of unique edges
            # will be the count of interactions.
            prop_vals = adata.uns[uns_key].loc[:, label_set].values
            edge_list = list(get_between_spot_edge_array(neighbourhood_bcs,
                                                    neighbourhood_indices,
                                     neigh_bool, True,
                                            cell_data=prop_vals, cutoff=cutoff))

    # Absolute mode
    else:
        # Need to consider the same problem indicated above #
        cell_types = adata.obs.loc[:,obs_key].values
        prop_vals = np.zeros( (len(cell_types), len(label_set)) )
        for i, cell_type in enumerate(label_set):
            prop_vals[:,i] = (cell_types==cell_type).astype(np.int_)
        edge_list = list(get_between_spot_edge_array(neighbourhood_bcs,
                                                neighbourhood_indices,
                                         neigh_bool, True, cell_data=prop_vals))

    if return_edges:
        return edge_list
    else: # Counting number of unique interactions #
        return len(edge_list)

def count_interactions(adata, all_set, mix_mode, neighbours, obs_key,
                       sig_bool, gene1_bool, gene2_bool,
                       tissue_types=None, cell_type_props=None,
                       cell_prop_cutoff=None, trans_dir=True,
                       ):
    # if trans_dir, rows are transmitter cell, cols receiver, otherwise reverse.
    int_matrix = np.zeros((len(all_set), len(all_set)), dtype=int)
    for i, cell_A in enumerate(all_set):  # transmitter if trans_dir else reciever
        # Determining which spots have cell type A #
        if not mix_mode:
            A_bool = tissue_types == cell_A
        else:
            col_A = [col for i, col in enumerate(cell_type_props.columns)
                     if cell_A in col][0]
            A_bool = cell_type_props.loc[:, col_A].values > cell_prop_cutoff

        A_gene1_bool = np.logical_and(A_bool, gene1_bool)
        A_gene1_sig_bool = np.logical_and(A_gene1_bool, sig_bool)
        A_gene1_sig_indices = np.where(A_gene1_sig_bool)[0]

        for j, cell_B in enumerate(all_set): # receiver if trans_dir else transmitter
            cellA_cellB_counts = count_core(adata, obs_key, neighbours,
                                      spot_indices=A_gene1_sig_indices,
                                      neigh_bool=gene2_bool, label_set=[cell_B],
                                                         spot_mixtures=mix_mode)
            int_matrix[i, j] = cellA_cellB_counts

    return int_matrix if trans_dir else int_matrix.transpose()

def get_interactions(adata, all_set, mix_mode, neighbours, obs_key,
                       sig_bool, gene1_bool, gene2_bool,
                       spot_mixtures: bool=False,
                       tissue_types=None, cell_type_props=None,
                       cell_prop_cutoff=None, trans_dir = True,
                     ):
    """"""
    interaction_edges = {}
    for i, cell_A in enumerate(all_set):  # transmitter if trans_dir else reciever
        # Determining which spots have cell type A #
        if not mix_mode:
            A_bool = tissue_types == cell_A
        else:
            col_A = [col for i, col in enumerate(cell_type_props.columns)
                     if cell_A in col][0]
            A_bool = cell_type_props.loc[:, col_A].values > cell_prop_cutoff

        A_gene1_bool = np.logical_and(A_bool, gene1_bool)
        A_gene1_sig_bool = np.logical_and(A_gene1_bool, sig_bool)
        A_gene1_sig_indices = np.where(A_gene1_sig_bool)[0]

        if trans_dir:
            interaction_edges[cell_A] = {}

        for j, cell_B in enumerate(all_set):  # receiver if trans_dir else transmitter
            edges_list = count_core(adata, obs_key, neighbours,
                                            spot_indices=A_gene1_sig_indices,
                                            neigh_bool=gene2_bool,
                                            label_set=[cell_B],
                                            return_edges=True,
                                            spot_mixtures=spot_mixtures)

            if trans_dir:
                interaction_edges[cell_A][cell_B] = edges_list
            else:
                if cell_B not in interaction_edges:
                    interaction_edges[cell_B] = {}
                interaction_edges[cell_B][cell_A] = edges_list

    return interaction_edges

def create_grids(adata: AnnData, num_row: int, num_col: int, radius: int = 1):
    """Generate screening grids across the tissue sample
    Parameters
    ----------
    adata: AnnData          The data object to generate grids on
    num_row: int            Number of rows
    num_col: int            Number of columns
    radius: int             Radius to determine neighbours (default: 1, nearest)

    Returns
    -------
    grids                 The individual grids defined by left and upper side
    width                   Width of grids
    height                  Height of grids
    """

    from itertools import chain

    coor = adata.obs[["imagerow", "imagecol"]]
    max_x = max(coor["imagecol"])
    min_x = min(coor["imagecol"])
    max_y = max(coor["imagerow"])
    min_y = min(coor["imagerow"])
    width = (max_x - min_x) / num_col
    height = (max_y - min_y) / num_row
    grids, neighbours = [], []
    # generate grids from top to bottom and left to right
    for n in range(num_row * num_col):
        neighbour = []
        x = min_x + n // num_row * width  # left side
        y = min_y + n % num_row * height  # upper side
        grids.append([x, y])

        # get neighbouring grids
        row = n % num_row
        col = n // num_row
        a = np.arange(num_row * num_col).reshape(num_col, num_row).T
        nb_matrix = [
            [
                a[i][j] if 0 <= i < a.shape[0] and 0 <= j < a.shape[1] else -1
                for j in range(col - radius, col + 1 + radius)
            ]
            for i in range(row - radius, row + 1 + radius)
        ]
        for item in nb_matrix:
            neighbour = chain(neighbour, item)
        neighbour = list(set(list(neighbour)))
        neighbours.append(
            [
                grid
                for grid in neighbour
                if not (grid == n and radius > 0) and grid != -1
            ]
        )

    return grids, width, height, neighbours


def count_grid(
    adata: AnnData,
    num_row: int = 30,
    num_col: int = 30,
    use_label: str = None,
    use_het: str = "cci_het_grid",
    radius: int = 1,
    verbose: bool = True,
) -> AnnData:
    """Count the cell type densities
    Parameters
    ----------
    adata: AnnData          The data object including the cell types to count
    num_row: int            Number of grids on height
    num_col: int            Number of grids on width
    use_label:         The cell type results to use in counting
    use_het:                The stoarge place for result
    radius: int             Distance to determine the neighbour grids (default: 1=nearest), radius=0 means within grid

    Returns
    -------
    adata: AnnData          With the counts of specified clusters in each grid of the tissue stored as adata.uns['het']
    """

    coor = adata.obs[["imagerow", "imagecol"]]
    grids, width, height, neighbours = create_grids(adata, num_row, num_col, radius)
    counts = pd.DataFrame(0, range(len(grids)), ["CT"])
    for n, grid in enumerate(grids):
        spots = coor[
            (coor["imagecol"] > grid[0])
            & (coor["imagecol"] < grid[0] + width)
            & (coor["imagerow"] < grid[1])
            & (coor["imagerow"] > grid[1] - height)
        ]
        counts.loc[n] = (adata.obsm[use_label].loc[spots.index] > 0.2).sum().sum()
    adata.obsm[use_het] = (counts / counts.max())["CT"]

    if verbose:
        print(
            "Counts for cluster (cell type) diversity stored into data.uns['"
            + use_het
            + "']"
        )

    return adata
