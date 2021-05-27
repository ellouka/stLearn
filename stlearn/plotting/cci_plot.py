from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
import matplotlib
import pandas as pd
import numpy as np
from numba.typed import List
import seaborn as sns
import sys
from anndata import AnnData
from typing import Optional, Union

from typing import Optional, Union, Mapping  # Special
from typing import Sequence, Iterable  # ABCs
from typing import Tuple  # Classes

import warnings

from .classes import CciPlot, LrResultPlot
from .classes_bokeh import BokehCciPlot
from ._docs import doc_spatial_base_plot, doc_het_plot, doc_lr_plot
from ..utils import Empty, _empty, _AxesSubplot, _docs_params
from .utils import get_cmap, check_cmap
from .cluster_plot import cluster_plot
from .deconvolution_plot import deconvolution_plot
from .gene_plot import gene_plot
from ..tools.microenv.cci.het import get_between_spot_edge_array

from bokeh.io import push_notebook, output_notebook
from bokeh.plotting import show

#@_docs_params(het_plot=doc_lr_plot)
def lr_plot(
    adata: AnnData, lr: str,
    min_expr: float = 0, sig_spots=True,
    use_label: str = None, use_mix: str = None, outer_mode: str = 'continuous',
    l_cmap=None, r_cmap=None, lr_cmap=None, inner_cmap=None,
    inner_size_prop: float=0.25, middle_size_prop: float=0.5,
    outer_size_prop: float=1, pt_scale: int=100, title='',
    show_image: bool=True, show_arrows: bool=False,
    fig: Figure = None, ax: Axes=None, crop: bool = True, margin: float = 100,
    # plotting params
    **kwargs,
) -> Optional[AnnData]:

    # Input checking #
    l, r = lr.split('_')
    ran_lr = 'lr_summary' in adata.uns
    ran_sig = False if not ran_lr else 'n_spots_sig' in adata.uns['lr_summary'].columns
    if ran_lr and lr in adata.uns['lr_summary'].index:
        if ran_sig:
            lr_sig = adata.uns['lr_summary'].loc[lr, :].values[1] > 0
        else:
            lr_sig = True
    else:
        lr_sig = False

    if sig_spots and not ran_lr:
        raise Exception("No LR results testing results found, "
                      "please run st.tl.cci.run first, or set sig_spots=False.")

    elif sig_spots and not lr_sig:
        raise Exception("LR has no significant spots, to visualise anyhow set"
                        "sig_spots=False")

    # Getting which are the allowed stats for the lr to plot #
    if not ran_sig:
        lr_use_labels = ['lr_scores']
    else:
        lr_use_labels = ['lr_scores', 'p_val', 'p_adj', '-log10(p_adj)', 'lr_sig_scores']

    if type(use_mix)!=type(None) and use_mix not in adata.uns:
        raise Exception(f"Specified use_mix, but no deconvolution results added "
                       "to adata.uns matching the use_mix ({use_mix}) key.")
    elif type(use_label)!=type(None) and use_label in lr_use_labels \
            and ran_sig and not lr_sig:
        raise Exception(f"Since use_label refers to lr stats & ran permutation testing, "
                        f"LR needs to be significant to view stats.")
    elif type(use_label)!=type(None) and use_label not in adata.obs.keys() \
                                             and use_label not in lr_use_labels:
        raise Exception(f"use_label must be in adata.obs or "
                        f"one of lr stats: {lr_use_labels}.")

    out_options = ['binary', 'continuous', None]
    if outer_mode not in out_options:
        raise Exception(f"{outer_mode} should be one of {out_options}")

    if l not in adata.var_names or r not in adata.var_names:
        raise Exception("L or R not found in adata.var_names.")

    # Whether to show just the significant spots or all spots
    if sig_spots:
        lr_results = adata.uns['per_lr_results'][lr]
        sig_bool = lr_results.loc[:, 'lr_sig_scores'].values != 0
        adata_full = adata
        adata = adata[sig_bool,:]
    else:
        sig_bool = np.array([True]*len(adata))
        adata_full = adata

    # Dealing with the axis #
    if type(fig)==type(None) or type(ax)==type(None):
        fig, ax = plt.subplots()

    l_expr = adata[:, l].X.toarray()[:, 0]
    r_expr = adata[:, r].X.toarray()[:, 0]
    # Adding binary points of the ligand/receptor pair #
    if outer_mode == 'binary':
        l_bool, r_bool = l_expr > min_expr, r_expr > min_expr
        lr_binary_labels = []
        for i in range(len(l_bool)):
            if l_bool[i] and not r_bool[i]:
                lr_binary_labels.append( l )
            elif not l_bool[i] and r_bool[i]:
                lr_binary_labels.append( r )
            elif l_bool[i] and r_bool[i]:
                lr_binary_labels.append( lr )
            else:
                lr_binary_labels.append( '' )
        lr_binary_labels = pd.Series(np.array(lr_binary_labels),
                                       index=adata.obs_names).astype('category')
        adata.obs[f'{lr}_binary_labels'] = lr_binary_labels

        if type(lr_cmap) == type(None):
            lr_cmap = "default" #This gets ignored due to setting colours below
            adata.uns[f'{lr}_binary_labels_set'] = [l, r, lr, '']
            adata.uns[f'{lr}_binary_labels_colors'] = \
                [matplotlib.colors.to_hex('r'), matplotlib.colors.to_hex('limegreen'),
                 matplotlib.colors.to_hex('b'), matplotlib.colors.to_hex('k')]
        else:
            lr_cmap = check_cmap(lr_cmap)

        cluster_plot(adata, use_label=f'{lr}_binary_labels', cmap=lr_cmap,
                           size=outer_size_prop * pt_scale, crop=False,
                           ax=ax, fig=fig, show_image=show_image, **kwargs)

    # Showing continuous gene expression of the LR pair #
    elif outer_mode == 'continuous':
        if type(l_cmap)==type(None):
            l_cmap = matplotlib.colors.LinearSegmentedColormap.from_list('lcmap',
                                                                [(0, 0, 0),
                                                                 (.5, 0, 0),
                                                                 (.75, 0, 0),
                                                                 (1, 0, 0)])
        else:
            l_cmap = check_cmap(l_cmap)
        if type(r_cmap)==type(None):
            r_cmap = matplotlib.colors.LinearSegmentedColormap.from_list('rcmap',
                                                                [(0, 0, 0),
                                                                 (0, .5, 0),
                                                                 (0, .75, 0),
                                                                 (0, 1, 0)])
        else:
            r_cmap = check_cmap(r_cmap)

        gene_plot(adata, gene_symbols=l, size=outer_size_prop * pt_scale,
               cmap=l_cmap, color_bar_label=l, ax=ax, fig=fig, crop=False,
                                                show_image=show_image, **kwargs)
        gene_plot(adata, gene_symbols=r, size=middle_size_prop * pt_scale,
               cmap=r_cmap, color_bar_label=r, ax=ax, fig=fig, crop=False,
                                                show_image=show_image, **kwargs)

    # Adding the cell type labels #
    if type(use_label) != type(None):
        if use_label in lr_use_labels:
            inner_cmap = inner_cmap if type(inner_cmap) != type(None) else "copper"
            adata.obsm[f'{lr}_{use_label}'] = adata.uns['per_lr_results'][
                                     lr].loc[adata.obs_names,use_label].values
            het_plot(adata, use_het=f'{lr}_{use_label}', show_image=show_image,
                     cmap=inner_cmap, crop=False,
                     ax=ax, fig=fig, size=inner_size_prop * pt_scale, **kwargs)
        else:
            inner_cmap = inner_cmap if type(inner_cmap)!=type(None) else "default"
            cluster_plot(adata, use_label=use_label, cmap=inner_cmap,
                         size=inner_size_prop * pt_scale, crop=False,
                         ax=ax, fig=fig, show_image=show_image, **kwargs)

    # Adding in labels which show the interactions between signicant spots &
    # neighbours
    if show_arrows:
        l_expr = adata_full[:, l].X.toarray()[:, 0]
        r_expr = adata_full[:, r].X.toarray()[:, 0]
        add_arrows(adata_full, l_expr > min_expr, r_expr>min_expr, sig_bool, ax)

    # Cropping #
    if crop:
        image_coor = adata.obsm["spatial"]
        imagecol = image_coor[:, 0]
        imagerow = image_coor[:, 1]
        ax.set_xlim(imagecol.min() - margin, imagecol.max() + margin)
        ax.set_ylim(imagerow.min() - margin, imagerow.max() + margin)
        ax.set_ylim(ax.get_ylim()[::-1])

    plt.title(title)

def add_arrows(adata: AnnData, L_bool: np.array, R_bool: np.array,
               sig_bool: np.array, ax: Axes):
    """ Adds arrows to the current plot for significant spots to neighbours \
        which is interacting with.
        Parameters
        ----------
        adata: AnnData          The anndata object.
        L_bool: np.array
        Returns
        -------
        counts: int   Total number of interactions satisfying the conditions, \
                      or np.array<set> if return_edges=True, where each set is \
                      an edge, only returns unique edges.
    """
    # Determining the neighbour spots used for significance testing #
    neighbours = List()
    for i in range(adata.uns['spot_neighbours'].shape[0]):
        neighs = np.array(adata.uns['spot_neighbours'].values[i,
                          :][0].split(','))
        neighs = neighs[neighs != ''].astype(int)
        neighbours.append(neighs)

    library_id = list(adata.uns["spatial"].keys())[0]
    # TODO the below could cause issues by hardcoding tissue res. #
    scale_factor = adata.uns['spatial'][library_id]['scalefactors'] \
                                                        ['tissue_lowres_scalef']
    scale_factor = 1

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
    all_edges_unique = []
    for edge in all_edges:
        if edge not in all_edges_unique:
            all_edges_unique.append(edge)

    # Now performing the plotting #
    # The arrows #
    # Now converting the edges to coordinates #
    for edge in all_edges_unique:
        cols = ['imagecol', 'imagerow']
        x1, y1 = adata.obs.loc[edge[0], cols].values.astype(float) * scale_factor
        x2, y2 = adata.obs.loc[edge[1], cols].values.astype(float) * scale_factor
        dx, dy = x2-x1, y2-y1
        ax.arrow(x1, y1, dx, dy, head_width=4)

@_docs_params(spatial_base_plot=doc_spatial_base_plot, het_plot=doc_het_plot)
def het_plot(
    adata: AnnData,
    # plotting param
    title: Optional["str"] = None,
    figsize: Optional[Tuple[float, float]] = None,
    cmap: Optional[str] = "Spectral_r",
    use_label: Optional[str] = None,
    list_clusters: Optional[list] = None,
    ax: Optional[matplotlib.axes._subplots.Axes] = None,
    fig: Optional[matplotlib.figure.Figure] = None,
    show_plot: Optional[bool] = True,
    show_axis: Optional[bool] = False,
    show_image: Optional[bool] = True,
    show_color_bar: Optional[bool] = True,
    crop: Optional[bool] = True,
    margin: Optional[bool] = 100,
    size: Optional[float] = 7,
    image_alpha: Optional[float] = 1.0,
    cell_alpha: Optional[float] = 1.0,
    use_raw: Optional[bool] = False,
    fname: Optional[str] = None,
    dpi: Optional[int] = 120,
    # cci param
    use_het: Optional[str] = "het",
    contour: bool = False,
    step_size: Optional[int] = None,
    vmin: float = None, vmax: float = None,
) -> Optional[AnnData]:

    """\
    Allows the visualization of significant cell-cell interaction
    as the values of dot points or contour in the Spatial
    transcriptomics array.


    Parameters
    -------------------------------------
    {spatial_base_plot}
    {het_plot}

    Examples
    -------------------------------------
    >>> import stlearn as st
    >>> adata = st.datasets.example_bcba()
    >>> pvalues = "lr_pvalues"
    >>> st.pl.gene_plot(adata, use_het = pvalues)

    """

    CciPlot(
        adata,
        title=title,
        figsize=figsize,
        cmap=cmap,
        use_label=use_label,
        list_clusters=list_clusters,
        ax=ax,
        fig=fig,
        show_plot=show_plot,
        show_axis=show_axis,
        show_image=show_image,
        show_color_bar=show_color_bar,
        crop=crop,
        margin=margin,
        size=size,
        image_alpha=image_alpha,
        cell_alpha=cell_alpha,
        use_raw=use_raw,
        fname=fname,
        dpi=dpi,
        use_het=use_het,
        contour=contour,
        step_size=step_size,
        vmin=vmin, vmax=vmax,
    )

def lr_result_plot(
        adata: AnnData,
        use_lr: Optional["str"] = None,
        use_result: Optional["str"] = "lr_sig_scores",
        # plotting param
        title: Optional["str"] = None,
        figsize: Optional[Tuple[float, float]] = None,
        cmap: Optional[str] = "Spectral_r",
        list_clusters: Optional[list] = None,
        ax: Optional[matplotlib.axes._subplots.Axes] = None,
        fig: Optional[matplotlib.figure.Figure] = None,
        show_plot: Optional[bool] = True,
        show_axis: Optional[bool] = False,
        show_image: Optional[bool] = True,
        show_color_bar: Optional[bool] = True,
        crop: Optional[bool] = True,
        margin: Optional[bool] = 100,
        size: Optional[float] = 7,
        image_alpha: Optional[float] = 1.0,
        cell_alpha: Optional[float] = 1.0,
        use_raw: Optional[bool] = False,
        fname: Optional[str] = None,
        dpi: Optional[int] = 120,
        # cci param
        contour: bool = False,
        step_size: Optional[int] = None,
        vmin: float = None, vmax: float = None,
):
    LrResultPlot(
        adata,
        use_lr,
        use_result,
        # plotting param
        title,
        figsize,
        cmap,
        list_clusters,
        ax,
        fig,
        show_plot,
        show_axis,
        show_image,
        show_color_bar,
        crop,
        margin,
        size,
        image_alpha,
        cell_alpha,
        use_raw,
        fname,
        dpi,
        # cci param
        contour,
        step_size,
        vmin, vmax,
    )


def het_plot_interactive(adata: AnnData):
    bokeh_object = BokehCciPlot(adata)
    output_notebook()
    show(bokeh_object.app, notebook_handle=True)


def grid_plot(
    adata: AnnData,
    use_het: str = None,
    num_row: int = 10,
    num_col: int = 10,
    vmin: float = None,
    vmax: float = None,
    cropped: bool = True,
    margin: int = 100,
    dpi: int = 100,
    name: str = None,
    output: str = None,
    copy: bool = False,
) -> Optional[AnnData]:

    """
    Cell diversity plot for sptial transcriptomics data.

    Parameters
    ----------
    adata:                  Annotated data matrix.
    use_het:                Cluster heterogeneity count results from tl.cci.het
    num_row: int            Number of grids on height
    num_col: int            Number of grids on width
    cropped                 crop image or not.
    margin                  margin used in cropping.
    dpi:                    Set dpi as the resolution for the plot.
    name:                   Name of the output figure file.
    output:                 Save the figure as file or not.
    copy:                   Return a copy instead of writing to adata.

    Returns
    -------
    Nothing
    """

    try:
        import seaborn as sns
    except:
        raise ImportError("Please run `pip install seaborn`")
    plt.subplots()

    sns.heatmap(
        pd.DataFrame(np.array(adata.obsm[use_het]).reshape(num_col, num_row)).T,
        vmin=vmin,
        vmax=vmax,
    )
    plt.axis("equal")

    if output is not None:
        plt.savefig(
            output + "/" + name + "_heatmap.pdf",
            dpi=dpi,
            bbox_inches="tight",
            pad_inches=0,
        )

    plt.show()
