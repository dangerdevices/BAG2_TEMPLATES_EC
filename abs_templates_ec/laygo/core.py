# -*- coding: utf-8 -*-

"""This module defines LaygoBase, a base template class for generic digital layout topologies."""

import abc
from typing import TYPE_CHECKING, Dict, Any, Set, Tuple, List, Optional, Iterable

import bisect

from bag.math import lcm
from bag.util.interval import IntervalSet

from bag.layout.util import BBox
from bag.layout.template import TemplateBase
from bag.layout.objects import Instance
from bag.layout.routing import TrackID

from .tech import LaygoTech
from .base import LaygoPrimitive, LaygoSubstrate, LaygoEndRow, LaygoSpace
from ..analog_core.placement import WireGroup, WireTree

if TYPE_CHECKING:
    from bag.layout.template import TemplateDB
    from bag.layout.routing import RoutingGrid


class LaygoIntvSet(object):
    """A data structure that keeps track of used laygo columns in a laygo row.

    This class is used to automatically fill empty spaces, and also get
    left/right/top/bottom layout information needed to create space blocks
    and extension rows.

    Note: We intentionally did not keep track of total number of columns in
    thie object.  This makes it possible to dynamically size a laygo row.

    Parameters
    ----------
    default_end_info : Any
        the default left/right edge layout information object to use.
    """

    def __init__(self, default_end_info):
        # type: (Any) -> None
        self._intv = IntervalSet()
        self._end_flags = {}
        self._default_end_info = default_end_info

    def add(self, intv, ext_info, endl, endr):
        # type: (Tuple[int, int], Any, Any, Any) -> bool
        """Add a new interval to this data structure.

        Parameters
        ----------
        intv : Tuple[int, int]
            the laygo interval as (start_column, stop_column) tuple.
        ext_info : Any
            the top/bottom extension information object of this interval.
        endl : Any
            the left edge layout information object.
        endr : Any
            the right edge layout information object.

        Returns
        -------
        success : bool
            True if the given interval is successfully added.  False if it
            overlaps with existing blocks.
        """
        ans = self._intv.add(intv, val=ext_info)
        if ans:
            start, stop = intv
            if start in self._end_flags:
                del self._end_flags[start]
            else:
                self._end_flags[start] = endl
            if stop in self._end_flags:
                del self._end_flags[stop]
            else:
                self._end_flags[stop] = endr
            return True
        else:
            return False

    def values(self):
        # type: () -> Iterable[Any]
        """Returns an iterator over extension information objects stored in this row."""
        return self._intv.values()

    def get_complement(self, total_intv, endl_info, endr_info):
        # type: (Tuple[int, int], Any, Any) -> Tuple[List[Tuple[int, int]], List[Tuple[Any, Any]]]
        """Returns a list of unused column intervals.

        Parameters
        ----------
        total_intv : Tuple[int, int]
            A (start, stop) tuple that indicates how many columns are in this row.
        endl_info : Any
            the left-most edge layout information object of this row.
        endr_info : Any
            the right-most edge layout information object of this row.

        Returns
        -------
        intv_list : List[Tuple[int, int]]
            a list of unused column intervals.
        end_list : List[Tuple[Any, Any]]
            a list of left/right edge layout information object corresponding to each
            unused interval.
        """
        compl_intv = self._intv.get_complement(total_intv)
        intv_list = []
        end_list = []
        for intv in compl_intv:
            intv_list.append(intv)
            end_list.append((self._end_flags.get(intv[0], endl_info),
                             self._end_flags.get(intv[1], endr_info)))
        return intv_list, end_list

    def get_end_info(self, num_col):
        # type: (int) -> Tuple[Any, Any]
        """Returns the left-most and right-most edge layout information object of this row.

        Parameters
        ----------
        num_col : int
            number of columns in this row.

        Returns
        -------
        endl_info : Any
            the left-most edge layout information object of this row.
        endr_info : Any
            the right-most edge layout information object of this row.
        """
        if 0 not in self._end_flags:
            endl_info = self._default_end_info
        else:
            endl_info = self._end_flags[0]

        if num_col not in self._end_flags:
            endr_info = self._default_end_info
        else:
            endr_info = self._end_flags[num_col]

        return endl_info, endr_info

    def get_end(self):
        # type: () -> int
        """Returns the end column index of the last used interval."""
        if not self._intv:
            return 0
        return self._intv.get_end()


class LaygoBaseInfo(object):
    """A class that provides information to assist in LaygoBase layout calculations.

    Parameters
    ----------
    grid : RoutingGrid
        the RoutingGrid object.
    config : Dict[str, Any]
        the LaygoBase configuration dictionary.
    top_layer : Optional[int]
        the LaygoBase top layer ID.
    guard_ring_nf : int
        guard ring width in number of fingers.  0 to disable.
    draw_boundaries : bool
        True if boundary cells should be drawn around this LaygoBase.
    end_mode : int
        right/left/top/bottom end mode flag.  This is a 4-bit integer.  If bit 0 (LSB) is 1, then
        we assume there are no blocks abutting the bottom.  If bit 1 is 1, we assume there are no
        blocks abutting the top.  bit 2 and bit 3 (MSB) corresponds to left and right, respectively.
        The default value is 15, which means we assume this AnalogBase is surrounded by empty
        spaces.
    num_col : Optional[int]
        number of columns in this LaygoBase.  This must be specified if draw_boundaries is True.
    """

    def __init__(self, grid, config, top_layer=None, guard_ring_nf=0, draw_boundaries=False,
                 end_mode=0, num_col=None):
        # type: (RoutingGrid, Dict[str, Any], Optional[int], int, bool, int, Optional[int]) -> None
        self._tech_cls = grid.tech_info.tech_params['layout']['laygo_tech_class']  # type: LaygoTech

        # error checking
        dig_top_layer = config['tr_layers'][-1]
        if dig_top_layer != self._tech_cls.get_dig_top_layer():
            raise ValueError('Top tr_layers must be layer %d' % self._tech_cls.get_dig_top_layer())

        # update routing grid
        lch_unit = int(round(config['lch'] / grid.layout_unit / grid.resolution))
        self.grid = grid.copy()
        self._lch_unit = lch_unit
        self._config = config

        sd_pitch = self._tech_cls.get_sd_pitch(lch_unit)
        vm_layer = self._tech_cls.get_dig_conn_layer()
        vm_space, vm_width = self._tech_cls.get_laygo_conn_track_info(self._lch_unit)
        self.grid.add_new_layer(vm_layer, vm_space, vm_width, 'y', override=True, unit_mode=True)
        tdir = 'x'
        for lay, w, sp in zip(self._config['tr_layers'], self._config['tr_widths'],
                              self._config['tr_spaces']):
            self.grid.add_new_layer(lay, sp, w, tdir, override=True, unit_mode=True)
            if tdir == 'y':
                pitch = w + sp
                if pitch % sd_pitch != 0:
                    raise ValueError('laygo vertical routing pitch must '
                                     'be multiples of %d' % sd_pitch)
                tdir = 'x'
            else:
                tdir = 'y'
        self.grid.update_block_pitch()

        # update routing grid width overrides
        w_override = self._config.get('w_override', None)
        if w_override:
            for layer_id, w_lookup in w_override.items():
                for width_ntr, w_unit in w_lookup.items():
                    self.grid.add_width_override(layer_id, width_ntr, w_unit, unit_mode=True)

        # initialize parameters
        self.guard_ring_nf = guard_ring_nf
        self.top_layer = dig_top_layer + 1 if top_layer is None else top_layer
        self.end_mode = end_mode
        self._col_width = self._tech_cls.get_sd_pitch(self._lch_unit)
        self.draw_boundaries = draw_boundaries

        # set number of columns
        self._num_col = None
        self._edge_margins = None
        self._edge_widths = None
        self.set_num_col(num_col)

    @property
    def tech_cls(self):
        return self._tech_cls

    @property
    def conn_layer(self):
        return self._tech_cls.get_dig_conn_layer()

    @property
    def fg2d_s_short(self):
        return self._tech_cls.get_laygo_fg2d_s_short()

    @property
    def sub_columns(self):
        return self._tech_cls.get_sub_columns(self._lch_unit)

    @property
    def sub_port_columns(self):
        return self._tech_cls.get_sub_port_columns(self._lch_unit)

    @property
    def min_sub_space(self):
        return self._tech_cls.get_min_sub_space_columns(self._lch_unit)

    @property
    def mos_pitch(self):
        return self._tech_cls.get_mos_pitch(unit_mode=True)

    @property
    def lch_unit(self):
        return self._lch_unit

    @property
    def lch(self):
        return self._lch_unit * self.grid.layout_unit * self.grid.resolution

    @property
    def col_width(self):
        return self._col_width

    @property
    def unit_num_col(self):
        blk_w = self.grid.get_block_size(self._tech_cls.get_dig_top_layer(), unit_mode=True)[0]
        col_width = self.col_width
        return lcm([blk_w, col_width]) // col_width

    @property
    def tot_height_pitch(self):
        return lcm([self.grid.get_block_size(self.top_layer, unit_mode=True)[1], self.mos_pitch])

    @property
    def num_col(self):
        return self._num_col

    @property
    def edge_margins(self):
        return self._edge_margins

    @property
    def edge_widths(self):
        return self._edge_widths

    @property
    def tot_width(self):
        if self._edge_margins is None:
            raise ValueError('Edge margins is not defined.  Did you set number of columns?')
        return (self._edge_margins[0] + self._edge_margins[1] + self._edge_widths[0] +
                self._edge_widths[1] + self._num_col * self._col_width)

    def get_placement_info(self, num_col):
        left_end = (self.end_mode & 4) != 0
        right_end = (self.end_mode & 8) != 0
        return self._tech_cls.get_placement_info(self.grid, self.top_layer, num_col, self._lch_unit,
                                                 self.guard_ring_nf, left_end, right_end, True)

    def set_num_col(self, new_num_col):
        if new_num_col is not None:
            if new_num_col % self.unit_num_col != 0:
                raise ValueError('num_col = %d must be '
                                 'multiple of %d' % (new_num_col, self.unit_num_col))
        self._num_col = new_num_col

        if self.draw_boundaries:
            if new_num_col is None:
                self._edge_margins = None
                self._edge_widths = None
            else:
                placement_info = self.get_placement_info(new_num_col)
                self._edge_margins = placement_info.edge_margins
                self._edge_widths = placement_info.edge_widths
        else:
            self._edge_margins = (0, 0)
            self._edge_widths = (0, 0)

    def __getitem__(self, item):
        return self._config[item]

    def col_to_coord(self, col_idx, ds_type, unit_mode=False):
        if self._edge_margins is None:
            raise ValueError('Edge margins is not defined.  Did you set number of columns?')

        ans = self._edge_margins[0] + self._edge_widths[0] + col_idx * self._col_width
        if ds_type == 'd':
            ans += self._col_width // 2

        if unit_mode:
            return ans
        return ans * self.grid.resolution

    def col_to_track(self, layer_id, col_idx, ds_type):
        # error checking
        dig_top_layer = self._tech_cls.get_dig_top_layer()
        if layer_id > dig_top_layer:
            raise ValueError('col_to_track() only works on layer <= %d' % dig_top_layer)
        if self.grid.get_direction(layer_id) == 'x':
            raise ValueError('col_to_track() only works on vertical routing layers.')

        coord = self.col_to_coord(col_idx, ds_type, unit_mode=True)
        return self.grid.coord_to_track(layer_id, coord, unit_mode=True)

    def col_to_nearest_rel_track(self, layer_id, col_idx, ds_type, half_track=False, mode=0):
        # error checking
        dig_top_layer = self._tech_cls.get_dig_top_layer()
        if layer_id > dig_top_layer:
            raise ValueError('col_to_nearest_rel_track() only works on layer <= %d' % dig_top_layer)
        if self.grid.get_direction(layer_id) == 'x':
            raise ValueError('col_to_nearest_rel_track() only works on vertical routing layers.')

        x_rel = col_idx * self._col_width
        if ds_type == 'd':
            x_rel += self._col_width // 2

        pitch = self.grid.get_track_pitch(layer_id, unit_mode=True)
        offset = pitch // 2
        if half_track:
            pitch //= 2

        q, r = divmod(x_rel - offset, pitch)
        if r == 0:
            # exactly on track
            if mode == -2:
                # move to lower track
                q -= 1
            elif mode == 2:
                # move to upper track
                q += 1
        else:
            # not on track
            if mode > 0 or (mode == 0 and r >= pitch / 2):
                # round up
                q += 1

        if not half_track:
            return q
        elif q % 2 == 0:
            return q // 2
        else:
            return q / 2

    def coord_to_col(self, coord, unit_mode=False):
        if self._edge_margins is None:
            raise ValueError('Edge margins is not defined.  Did you set number of columns?')

        if not unit_mode:
            coord = int(round(coord / self.grid.resolution))

        k = self._col_width // 2
        offset = self._edge_margins[0] + self._edge_widths[0]
        if (coord - offset) % k != 0:
            raise ValueError('Coordinate %d is not on pitch.' % coord)
        col_idx_half = (coord - offset) // k

        if col_idx_half % 2 == 0:
            return col_idx_half // 2, 's'
        else:
            return (col_idx_half - 1) // 2, 'd'

    def coord_to_nearest_col(self, coord, ds_type=None, mode=0, unit_mode=False):
        if self._edge_margins is None:
            raise ValueError('Edge margins is not defined.  Did you set number of columns?')

        if not unit_mode:
            coord = int(round(coord / self.grid.resolution))

        col_width = self._col_width
        col_width2 = col_width // 2
        offset = self._edge_margins[0] + self._edge_widths[0]
        if ds_type == 'd':
            offset += col_width2

        if ds_type is None:
            k = col_width2
        else:
            k = col_width

        coord -= offset
        if mode == 0:
            n = int(round(coord / k))
        elif mode > 0:
            if coord % k == 0 and mode == 2:
                coord += 1
            n = -(-coord // k)
        else:
            if coord % k == 0 and mode == -2:
                coord -= 1
            n = coord // k

        return self.coord_to_col(n * k + offset, unit_mode=True)

    def rel_track_to_nearest_col(self, layer_id, rel_tid, ds_type=None, mode=0):
        # error checking
        dig_top_layer = self._tech_cls.get_dig_top_layer()
        if layer_id > dig_top_layer:
            raise ValueError('rel_track_to_nearest_col() only works on layer <= %d' % dig_top_layer)
        if self.grid.get_direction(layer_id) == 'x':
            raise ValueError('rel_track_to_nearest_col() only works on vertical routing layers.')

        pitch = self.grid.get_track_pitch(layer_id, unit_mode=True)
        x_rel = pitch // 2 + int(round(rel_tid * pitch))

        col_width = self.col_width
        col_width2 = col_width // 2
        offset = 0
        if ds_type == 'd':
            offset += col_width2

        if ds_type is None:
            k = col_width2
        else:
            k = col_width

        x_rel -= offset
        if mode == 0:
            n = int(round(x_rel / k))
        elif mode > 0:
            if x_rel % k == 0 and mode == 2:
                x_rel += 1
            n = -(-x_rel // k)
        else:
            if x_rel % k == 0 and mode == -2:
                x_rel -= 1
            n = x_rel // k

        rel_coord = n * k + offset
        k = col_width2
        col_idx_half = rel_coord // k

        if col_idx_half % 2 == 0:
            return col_idx_half // 2, 's'
        else:
            return (col_idx_half - 1) // 2, 'd'


class LaygoBase(TemplateBase, metaclass=abc.ABCMeta):
    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **kwargs) -> None

        hidden_params = kwargs.pop('hidden_params', {}).copy()
        hidden_params['laygo_endl_infos'] = None
        hidden_params['laygo_endr_infos'] = None

        TemplateBase.__init__(self, temp_db, lib_name, params, used_names,
                              hidden_params=hidden_params, **kwargs)

        self._laygo_info = LaygoBaseInfo(self.grid, self.params['config'])
        self.grid = self._laygo_info.grid
        self._tech_cls = self._laygo_info.tech_cls

        # initialize attributes
        self._num_rows = 0
        self._laygo_size = None
        self._row_orientations = None
        self._row_min_tracks = None
        self._row_infos = None
        self._row_kwargs = None
        self._row_y = None
        self._ext_params = None
        self._used_list = None  # type: List[LaygoIntvSet]
        self._bot_end_master = None
        self._top_end_master = None
        self._ext_edge_infos = None
        self._bot_sub_extw = 0
        self._top_sub_extw = 0
        self._endl_infos = None
        self._endr_infos = None

    @property
    def laygo_info(self):
        # type: () -> LaygoBaseInfo
        return self._laygo_info

    @property
    def laygo_size(self):
        return self._laygo_size

    @property
    def conn_layer(self):
        return self._laygo_info.conn_layer

    @property
    def fg2d_s_short(self):
        return self._laygo_info.fg2d_s_short

    @property
    def sub_columns(self):
        return self._laygo_info.sub_columns

    @property
    def min_sub_space(self):
        return self._laygo_info.min_sub_space

    @property
    def tot_height(self):
        return self._row_y[-1][-1]

    def _get_track_intervals(self, hm_layer, orient, info, ycur, ybot, via_exty, ng, ngb, nds):
        if 'g_conn_y' in info:
            gyb, gyt = info['g_conn_y']
        else:
            gyb, gyt = ybot

        syb, syt = info['ds_conn_y']
        dyb, dyt = info['gb_conn_y']

        if orient == 'R0':
            gyb += ycur
            gyt += ycur
            syb += ycur
            syt += ycur
            dyb += ycur
            dyt += ycur

            gbtr = self.grid.coord_to_nearest_track(hm_layer, gyb + via_exty, half_track=True,
                                                    mode=1, unit_mode=True)
            gttr = self.grid.coord_to_nearest_track(hm_layer, gyt - via_exty, half_track=True,
                                                    mode=-1, unit_mode=True)
            g_intv = (min(gbtr, gttr + 1 - ng), gttr + 1)
            sbtr = self.grid.coord_to_nearest_track(hm_layer, syb + via_exty, half_track=True,
                                                    mode=1, unit_mode=True)
            sttr = self.grid.coord_to_nearest_track(hm_layer, syt - via_exty, half_track=True,
                                                    mode=-1, unit_mode=True)
            s_intv = (sbtr, max(sttr + 1, sbtr + nds))
            dbtr = self.grid.coord_to_nearest_track(hm_layer, dyb + via_exty, half_track=True,
                                                    mode=1, unit_mode=True)
            dttr = self.grid.coord_to_nearest_track(hm_layer, dyt - via_exty, half_track=True,
                                                    mode=-1, unit_mode=True)
            d_intv = (dbtr, max(dttr + 1, dbtr + ngb))
            yt_vm = max(syt, dyt)
        else:
            h = info['arr_y'][1]
            gyb, gyt = ycur + h - gyt, ycur + h - gyb
            dyb, dyt = ycur + h - dyt, ycur + h - dyb
            syb, syt = ycur + h - syt, ycur + h - syb

            gbtr = self.grid.coord_to_nearest_track(hm_layer, gyb + via_exty, half_track=True,
                                                    mode=1, unit_mode=True)
            gttr = self.grid.coord_to_nearest_track(hm_layer, gyt - via_exty, half_track=True,
                                                    mode=-1, unit_mode=True)
            g_intv = (gbtr, max(gttr + 1, gbtr + ng))
            sbtr = self.grid.coord_to_nearest_track(hm_layer, syb + via_exty, half_track=True,
                                                    mode=1, unit_mode=True)
            sttr = self.grid.coord_to_nearest_track(hm_layer, syt - via_exty, half_track=True,
                                                    mode=-1, unit_mode=True)
            s_intv = (min(sbtr, sttr + 1 - nds), sttr + 1)
            dbtr = self.grid.coord_to_nearest_track(hm_layer, dyb + via_exty, half_track=True,
                                                    mode=1, unit_mode=True)
            dttr = self.grid.coord_to_nearest_track(hm_layer, dyt - via_exty, half_track=True,
                                                    mode=-1, unit_mode=True)
            d_intv = (min(dbtr, dttr + 1 - ngb), dttr + 1)
            yt_vm = gyt

        tr_top = max(g_intv[1], d_intv[1], s_intv[1]) - 1
        yt_vm = max(yt_vm, self.grid.track_to_coord(hm_layer, tr_top, unit_mode=True) + via_exty)
        return g_intv, s_intv, d_intv, yt_vm

    def _set_endlr_infos(self, num_rows):
        default_end_info = self._tech_cls.get_default_end_info()
        self._endl_infos = self.params['laygo_endl_infos']
        if self._endl_infos is None:
            self._endl_infos = [default_end_info] * num_rows
        self._endr_infos = self.params['laygo_endr_infos']
        if self._endr_infos is None:
            self._endr_infos = [default_end_info] * num_rows

    def set_rows_direct(self, dig_row_info):
        default_end_info = self._tech_cls.get_default_end_info()

        # set LaygoInfo
        self._laygo_info.top_layer = dig_row_info['top_layer']
        self._laygo_info.guard_ring_nf = dig_row_info['guard_ring_nf']
        self._laygo_info.draw_boundaries = False
        self._laygo_info.end_mode = 0

        # set row information
        self._row_orientations = dig_row_info['row_orientations']
        self._num_rows = len(self._row_orientations)
        self._row_kwargs = dig_row_info['row_kwargs']
        self._row_min_tracks = dig_row_info['row_min_tracks']
        self._used_list = [LaygoIntvSet(default_end_info) for _ in range(self._num_rows)]
        self._row_infos = dig_row_info['row_infos']
        self._ext_params = dig_row_info['ext_params']
        self._row_y = dig_row_info['row_y']

        # set left and right end information list
        self._set_endlr_infos(self._num_rows)

    def set_row_types(self, row_types, row_widths, row_orientations, row_thresholds,
                      draw_boundaries, end_mode, num_g_tracks=None, num_gb_tracks=None,
                      num_ds_tracks=None, row_min_tracks=None, top_layer=None,
                      guard_ring_nf=0, row_kwargs=None, num_col=None, row_sub_widths=None,
                      **kwargs):

        tr_manager = kwargs.get('tr_manager', None)
        wire_names = kwargs.get('wire_names', None)
        min_height = kwargs.get('min_height', 0)

        # error checking
        if (row_types[0] == 'ptap' or row_types[0] == 'ntap') and row_orientations[0] != 'R0':
            raise ValueError('bottom substrate orientation must be R0')
        if (row_types[-1] == 'ptap' or row_types[-1] == 'ntap') and row_orientations[-1] != 'MX':
            raise ValueError('top substrate orientation must be MX')
        if len(row_types) < 2:
            raise ValueError('Must draw at least 2 rows.')
        if len(row_types) != len(row_widths) or len(row_types) != len(row_orientations):
            raise ValueError('row_types/row_widths/row_orientations length mismatch.')
        if draw_boundaries and num_col is None:
            raise ValueError('Must specify total number of columns if drawing boundary.')
        if not row_sub_widths:
            row_sub_widths = row_widths
        elif len(row_sub_widths) != len(row_widths):
            raise ValueError('row_widths and row_sub_widths must have same length.')

        # set default values
        num_rows = len(row_types)
        if not draw_boundaries:
            end_mode = 0
        if row_kwargs is None:
            row_kwargs = [{}] * num_rows
        if row_min_tracks is None:
            row_min_tracks = [{}] * num_rows
        if top_layer is None:
            top_layer = self._laygo_info.top_layer

        default_end_info = self._tech_cls.get_default_end_info()

        # set LaygoInfo
        self._laygo_info.top_layer = top_layer
        self._laygo_info.guard_ring_nf = guard_ring_nf
        self._laygo_info.draw_boundaries = draw_boundaries
        self._laygo_info.end_mode = end_mode
        self._laygo_info.set_num_col(num_col)

        # set known row information
        self._row_orientations = row_orientations
        self._num_rows = num_rows
        self._row_kwargs = row_kwargs
        self._row_min_tracks = row_min_tracks
        self._used_list = [LaygoIntvSet(default_end_info) for _ in range(self._num_rows)]

        # set left and right end information list
        self._set_endlr_infos(self._num_rows)

        # compute remaining row information
        tot_height_pitch = self._laygo_info.tot_height_pitch
        if draw_boundaries:
            bot_end = (end_mode & 1) != 0
            top_end = (end_mode & 2) != 0

            if row_types[0] != 'ntap' and row_types[0] != 'ptap':
                raise ValueError('Bottom row must be substrate.')
            if row_types[-1] != 'ntap' and row_types[-1] != 'ptap':
                raise ValueError('Top row must be substrate.')

            # create boundary masters
            params = dict(
                lch=self._laygo_info.lch,
                mos_type=row_types[0],
                threshold=row_thresholds[0],
                is_end=bot_end,
                top_layer=top_layer,
            )
            self._bot_end_master = self.new_template(params=params, temp_cls=LaygoEndRow)
            params = dict(
                lch=self._laygo_info.lch,
                mos_type=row_types[-1],
                threshold=row_thresholds[-1],
                is_end=top_end,
                top_layer=top_layer,
            )
            self._top_end_master = self.new_template(params=params, temp_cls=LaygoEndRow)
            ybot = self._bot_end_master.bound_box.height_unit
            min_height -= self._top_end_master.bound_box.height_unit
        else:
            ybot = 0

        tmp = self._get_place_info(row_types, row_widths, row_sub_widths, row_orientations,
                                   row_thresholds, row_min_tracks, row_kwargs, num_g_tracks,
                                   num_gb_tracks, num_ds_tracks, tr_manager, wire_names)
        pinfo_list, wire_tree = tmp

        result = self._place_rows(ybot, tot_height_pitch, pinfo_list, wire_tree,
                                  tr_manager, wire_names, min_height)

        # set remaining row information
        self._row_infos, self._ext_params, self._row_y = result

        # compute laygo size if we know the number of columns
        if num_col is not None:
            self.set_laygo_size(num_col)

    def get_digital_row_info(self):
        if not self.finalized:
            raise ValueError('Can only compute digital row info if this block is finalized.')
        if self._laygo_info.draw_boundaries is True:
            raise ValueError('LaygoBase with boundaries cannot be used in digital row.')

        mos_pitch = self._laygo_info.mos_pitch
        ans = dict(
            config=self.params['config'],
            top_layer=self._laygo_info.top_layer,
            guard_ring_nf=self._laygo_info.guard_ring_nf,
            row_orientations=self._row_orientations,
            row_kwargs=self._row_kwargs,
            row_min_tracks=self._row_min_tracks,
            row_infos=self._row_infos,
            ext_params=self._ext_params,
            row_y=self._row_y,
            row_height=self.bound_box.top_unit,
            bot_extw=(self._row_y[0][1] - self._row_y[0][0]) // mos_pitch,
            top_extw=(self._row_y[-1][3] - self._row_y[-1][2]) // mos_pitch,
            bot_sub_extw=self._bot_sub_extw,
            top_sub_extw=self._top_sub_extw,
            bot_ext_info=self._row_infos[0]['ext_bot_info'],
            top_ext_info=self._row_infos[-1]['ext_top_info'],
            row_edge_infos=self._get_row_edge_infos(),
            ext_edge_infos=self._ext_edge_infos,
        )
        return ans

    def _get_place_info(self, row_types, row_widths, row_sub_widths, row_orientations,
                        row_thresholds, row_min_tracks, row_kwargs, num_g_tracks,
                        num_gb_tracks, num_ds_tracks, tr_manager, wire_names):
        lch = self._laygo_info.lch
        lch_unit = int(round(lch / self.grid.layout_unit / self.grid.resolution))
        mos_pitch = self._laygo_info.mos_pitch
        tcls = self._tech_cls
        conn_layer = tcls.get_dig_conn_layer()
        hm_layer = conn_layer + 1
        le_sp_tr = self.grid.get_line_end_space_tracks(conn_layer, hm_layer, 1, half_space=True)

        pinfo_list = []
        wire_tree = WireTree(mirror=(row_types[0] == 'nch' or row_types[0] == 'pch'))
        for row_idx, (row_type, row_w, row_wsub, row_orient,
                      row_thres, min_tracks, kwargs) in \
                enumerate(zip(row_types, row_widths, row_sub_widths, row_orientations,
                              row_thresholds, row_min_tracks, row_kwargs)):
            if row_idx == 0:
                bot_row_type = row_type
            else:
                bot_row_type = row_types[row_idx - 1]
            if row_idx == len(row_types) - 1:
                top_row_type = row_type
            else:
                top_row_type = row_types[row_idx + 1]

            if row_orient != 'R0':
                bot_row_type, top_row_type = top_row_type, bot_row_type

            # get information dictionary
            if row_type == 'nch' or row_type == 'pch':
                row_info = tcls.get_laygo_mos_row_info(lch_unit, row_w, row_wsub, row_type,
                                                       row_thres, bot_row_type, top_row_type,
                                                       **kwargs)
            elif row_type == 'ptap' or row_type == 'ntap':
                row_info = tcls.get_laygo_sub_row_info(lch_unit, row_w, row_type,
                                                       row_thres, **kwargs)
            else:
                raise ValueError('Unknown row type: %s' % row_type)

            # get row pitch
            row_pitch = min_row_height = mos_pitch
            for layer, num_tr in min_tracks.items():
                tr_pitch = self.grid.get_track_pitch(layer, unit_mode=True)
                min_row_height = max(min_row_height, num_tr * tr_pitch)
                row_pitch = lcm([row_pitch, tr_pitch // 2])

            # get bottom/top Y coordinates
            g_conn_y = row_info.get('g_conn_y', (0, 0))
            gb_conn_y = row_info['gb_conn_y']
            ds_conn_y = row_info['ds_conn_y']
            bot_conn_y, top_conn_y, bot_wires, top_wires = [], [], [], []
            if row_orient == 'R0':
                bext_info = row_info['ext_bot_info']
                text_info = row_info['ext_top_info']
                if wire_names is None:
                    ng = num_g_tracks[row_idx]
                    ngb = num_gb_tracks[row_idx]
                    nds = num_ds_tracks[row_idx]
                    if ng >= 1:
                        bot_conn_y.append(g_conn_y)
                        bot_wires.append(WireGroup(hm_layer, ng, space=le_sp_tr))
                    if ngb >= 1:
                        top_conn_y.append(gb_conn_y)
                        top_wires.append(WireGroup(hm_layer, ngb, space=le_sp_tr))
                    if nds >= 1:
                        top_conn_y.append(ds_conn_y)
                        top_wires.append(WireGroup(hm_layer, nds, space=le_sp_tr))
                else:
                    wnames = wire_names[row_idx]
                    if wnames['g']:
                        bot_conn_y.append(g_conn_y)
                        bot_wires.append(WireGroup(hm_layer, tr_manager=tr_manager,
                                                   name_list=wnames['g']))
                    if wnames['gb']:
                        top_conn_y.append(gb_conn_y)
                        top_wires.append(WireGroup(hm_layer, tr_manager=tr_manager,
                                                   name_list=wnames['gb']))
                    if wnames['ds']:
                        top_conn_y.append(ds_conn_y)
                        top_wires.append(WireGroup(hm_layer, tr_manager=tr_manager,
                                                   name_list=wnames['ds']))
            else:
                bext_info = row_info['ext_top_info']
                text_info = row_info['ext_bot_info']
                if wire_names is None:
                    ng = num_g_tracks[row_idx]
                    ngb = num_gb_tracks[row_idx]
                    nds = num_ds_tracks[row_idx]
                    if ng >= 1:
                        top_conn_y.append(g_conn_y)
                        top_wires.append(WireGroup(hm_layer, ng, space=le_sp_tr))
                    if ngb >= 1:
                        bot_conn_y.append(gb_conn_y)
                        bot_wires.append(WireGroup(hm_layer, ngb, space=le_sp_tr))
                    if nds >= 1:
                        bot_conn_y.append(ds_conn_y)
                        bot_wires.append(WireGroup(hm_layer, nds, space=le_sp_tr))
                else:
                    wnames = wire_names[row_idx]
                    if wnames['g']:
                        top_conn_y.append(g_conn_y)
                        top_wires.append(WireGroup(hm_layer, tr_manager=tr_manager,
                                                   name_list=wnames['g']))
                    if wnames['gb']:
                        bot_conn_y.append(gb_conn_y)
                        bot_wires.append(WireGroup(hm_layer, tr_manager=tr_manager,
                                                   name_list=wnames['gb']))
                    if wnames['ds']:
                        bot_conn_y.append(ds_conn_y)
                        bot_wires.append(WireGroup(hm_layer, tr_manager=tr_manager,
                                                   name_list=wnames['ds']))

            if bot_wires:
                wire_tree.add_wires(bot_wires, (row_idx, 0))
            if top_wires:
                wire_tree.add_wires(top_wires, (row_idx, 1))
            pinfo_list.append((bot_conn_y, top_conn_y, row_info['arr_y'][1], row_orient,
                               bext_info, text_info, row_type, row_info, min_row_height,
                               row_pitch, kwargs))

        return pinfo_list, wire_tree

    def _place_with_num_tracks(self, tr_next, hm_layer, bot_conn_y, bot_wires, ytop_prev,
                               conn_delta, mos_pitch, tr_manager, last_track):

        # determine block placement
        ycur = ytop_prev
        tr_last_info = []
        for btr_info, (yb, yt) in zip(bot_wires, bot_conn_y):
            if isinstance(btr_info, int) or isinstance(btr_info, float):
                bot_ntr = btr_info
                if bot_ntr >= 1:
                    tr_last_info.append(tr_next + bot_ntr - 1)
            else:
                if btr_info:
                    bot_ntr, bot_loc = tr_manager.place_wires(hm_layer, btr_info, start_idx=tr_next)
                    tr_last_info.append((bot_loc[-1], btr_info[-1]))
                else:
                    bot_ntr = 0

            if bot_ntr >= 1:
                y_ttr = self.grid.track_to_coord(hm_layer, tr_next + bot_ntr - 1, unit_mode=True)
                ycur = max(ycur, y_ttr - yt + conn_delta)

        if not tr_last_info:
            tr_last_info = last_track

        # round Y coordinate to mos_pitch
        ycur = -(-ycur // mos_pitch) * mos_pitch
        return ycur, tr_last_info

    def _compute_ytop(self, tr_next, ycur, ytop, hm_layer, top_conn_y, top_wires, last_track,
                      conn_delta, vm_le_sp, row_pitch, tr_manager, next_wires, tr_sp_top):
        grid = self.grid

        if last_track:
            # update tr_next to account for space between bottom and top tracks
            for ltr in last_track:
                if isinstance(ltr, int) or isinstance(ltr, float):
                    tr_next = max(tr_next, ltr + 1)
                else:
                    has_top = False
                    for ttr_info in top_wires:
                        if ttr_info:
                            has_top = True
                            _, loc = tr_manager.place_wires(hm_layer, [ltr[1], ttr_info[0]])
                            tidx = loc[1] + ltr[0] - loc[0]
                            t_w = tr_manager.get_width(hm_layer, ttr_info[0])
                            tr_next = max(tr_next, tidx - (t_w - 1) / 2)
                    if not has_top and next_wires is not None:
                        for nw in next_wires:
                            _, loc = tr_manager.place_wires(hm_layer, [ltr[1], nw])
                            tidx = loc[1] + ltr[0] - loc[0]
                            t_w = tr_manager.get_width(hm_layer, nw)
                            tr_next = max(tr_next, tidx - (t_w - 1) / 2)

        tr_next_new = tr_next
        last_track_new = []
        for ttr_info, (yb, yt) in zip(top_wires, top_conn_y):
            ybtr = ycur + yb + conn_delta
            yttr = ycur + yt - conn_delta
            tr0 = max(tr_next, grid.coord_to_nearest_track(hm_layer, ybtr, half_track=True,
                                                           mode=1, unit_mode=True))
            tr1 = grid.coord_to_nearest_track(hm_layer, yttr, half_track=True,
                                              mode=-1, unit_mode=True)
            if isinstance(ttr_info, int) or isinstance(ttr_info, float):
                tr1 = max(tr1, tr0 + ttr_info - 1)
                tr1_y = grid.track_to_coord(hm_layer, tr1, unit_mode=True)
                tny = max(ycur + yt + vm_le_sp + conn_delta,
                          tr1_y + vm_le_sp + 2 * conn_delta)
                tn = grid.coord_to_nearest_track(hm_layer, tny, half_track=True,
                                                 mode=1, unit_mode=True)
                tn = max(tn, tr1 + tr_sp_top)
                tny = grid.track_to_coord(hm_layer, tn, unit_mode=True)
                ytop = max(ytop, (tny + tr1_y) // 2)
                tr_next_new = max(tr_next_new, tn)
                last_track_new.append(tr1)
            else:
                if ttr_info:
                    top_ntr, locs = tr_manager.place_wires(hm_layer, ttr_info, start_idx=tr0)
                    last_track_new.append((locs[-1], ttr_info[-1]))
                    if next_wires is None:
                        tr1 = max(tr1, tr0 + top_ntr - 1)
                        ytop = max(ytop, grid.track_to_coord(hm_layer, tr1 + 0.5, unit_mode=True))
                        tr_next_new = max(tr_next_new, tr1 + 1)
                    else:
                        for nw in next_wires:
                            t_w1 = tr_manager.get_width(hm_layer, ttr_info[-1])
                            t_w2 = tr_manager.get_width(hm_layer, nw)
                            _, locs = tr_manager.place_wires(hm_layer, ttr_info + [nw],
                                                             start_idx=tr0)
                            t_idx1 = locs[-2] + (t_w1 - 1) / 2
                            t_idx2 = locs[-1] - (t_w2 - 1) / 2
                            tr_next_new = max(tr_next_new, t_idx2)
                            ya = grid.track_to_coord(hm_layer, t_idx1, unit_mode=True)
                            yb = grid.track_to_coord(hm_layer, t_idx2, unit_mode=True)
                            ytop = max(ytop, (ya + yb) // 2)

        if not last_track_new:
            last_track_new = last_track

        return -(-ytop // row_pitch) * row_pitch, tr_next_new, last_track_new

    def _place_mirror_or_sub(self, row_type, row_thres, lch_unit, mos_pitch, ydelta, ext_info):
        # find substrate parameters
        sub_type = 'ntap' if row_type == 'pch' or row_type == 'ntap' else 'ptap'
        w_sub = self._laygo_info['w_sub']
        min_sub_tracks = self._laygo_info['min_sub_tracks']
        sub_info = self._tech_cls.get_laygo_sub_row_info(lch_unit, w_sub, sub_type, row_thres)
        sub_ext_info = sub_info['ext_top_info']

        # quantize substrate height to top layer pitch.
        sub_height = sub_info['arr_y'][1]
        min_sub_height = mos_pitch
        top_pitch = self.grid.get_track_pitch(self._laygo_info.top_layer, unit_mode=True)
        sub_pitch = lcm([mos_pitch, top_pitch])
        for layer, num_tr in min_sub_tracks:
            tr_pitch = self.grid.get_track_pitch(layer, unit_mode=True)
            min_sub_height = max(min_sub_height, num_tr * tr_pitch)
            sub_pitch = lcm([sub_pitch, tr_pitch])

        real_sub_height = max(sub_height, min_sub_height)
        real_sub_height = -(-real_sub_height // sub_pitch) * sub_pitch
        sub_extw = (real_sub_height - sub_height) // mos_pitch

        # repeat until we satisfy both substrate and mirror row constraint
        ext_w = -(-ydelta // mos_pitch)
        ext_w_valid = False
        while not ext_w_valid:
            ext_w_valid = True
            # check we satisfy substrate constraint
            valid_widths = self._tech_cls.get_valid_extension_widths(lch_unit, sub_ext_info,
                                                                     ext_info)
            ext_w_test = ext_w + sub_extw
            if ext_w_test < valid_widths[-1] and ext_w_test not in valid_widths:
                # did not pass substrate constraint, update extension width
                ext_w_valid = False
                ext_w_test = valid_widths[bisect.bisect_left(valid_widths, ext_w_test)]
                ext_w = ext_w_test - sub_extw
                continue

            # check we satisfy mirror extension constraint
            valid_widths = self._tech_cls.get_valid_extension_widths(lch_unit, ext_info, ext_info)
            ext_w_test = ext_w * 2
            if ext_w_test < valid_widths[-1] and ext_w_test not in valid_widths:
                # did not pass extension constraint, update extension width.
                ext_w_valid = False
                ext_w_test = valid_widths[bisect.bisect_left(valid_widths, ext_w_test)]
                ext_w = -(-ext_w_test // 2)

        return ext_w, sub_extw

    @classmethod
    def _get_next_wires(cls, idx, wire_names, pinfo_list):
        if wire_names is None:
            return None

        next_wires = []
        for i in range(idx + 1, len(pinfo_list)):
            for w_list in (pinfo_list[i][6], pinfo_list[i][7]):
                has_wire = False
                for tr_info in w_list:
                    if tr_info:
                        has_wire = True
                        next_wires.append(tr_info[0])
                if has_wire:
                    return next_wires

        return None

    @classmethod
    def _get_last_wires(cls, wire_names, pinfo_list):
        if wire_names is None:
            return None

        next_wires = []
        for i in range(len(pinfo_list), -1, -1):
            for w_list in (pinfo_list[i][7], pinfo_list[i][6]):
                has_wire = False
                for tr_info in w_list:
                    if tr_info:
                        has_wire = True
                        next_wires.append(tr_info[-1])
                if has_wire:
                    return next_wires

        return None

    def _place_rows(self, ybot, tot_height_pitch, pinfo_list, wire_tree, tr_manager, wire_names,
                    min_htot):
        lch_unit = self._laygo_info.lch_unit

        mos_pitch = self._tech_cls.get_mos_pitch(unit_mode=True)
        vm_layer = self._tech_cls.get_dig_conn_layer()
        hm_layer = vm_layer + 1
        vm_le_sp = self.grid.get_line_end_space(vm_layer, 1, unit_mode=True)

        ext_params_list = []
        row_infos = []
        row_y = []
        prev_ext_info = None
        prev_ext_h = 0
        ytop_prev = ybot
        last_track = []
        # first pass: determine Y coordinates of each row.
        for idx, (bot_conn_y, top_conn_y, blk_height, row_orient, ext_bot_info, ext_top_info,
                  row_type, row_info, min_row_height, row_pitch, kwargs) in enumerate(pinfo_list):

            row_thres = row_info['threshold']
            is_sub = (row_type == 'ptap' or row_type == 'ntap')

            # find Y coordinate of current block from track/mirror placement constraints
            if idx == 0 and is_sub:
                # bottom substrate has orientation R0 and no gate tracks, just abut to bottom.
                ycur = ytop_prev
                cur_bot_ext_h = 0
            else:
                ycur = ytop_prev
                wire_groups = wire_tree.get_wire_groups((idx, 0))
                if wire_groups is not None:
                    # find Y coordinate that allows us to connect to top bottom track
                    for (_, yt), wg in zip(bot_conn_y, wire_groups):
                        _, tr_idx, tr_w = wg.last_track
                        via_ext = self.grid.get_via_extensions(vm_layer, 1, tr_w, unit_mode=True)[0]
                        y_ttr = self.grid.get_wire_bounds(hm_layer, tr_idx, width=tr_w,
                                                          unit_mode=True)[1]
                        ycur = max(ycur, y_ttr + via_ext - yt)
                    ycur = -(-ycur // mos_pitch) * mos_pitch

                # make sure extension constraints is met
                if idx != 0:
                    valid_widths = self._tech_cls.get_valid_extension_widths(lch_unit, ext_bot_info,
                                                                             prev_ext_info)
                    cur_bot_ext_h = (ycur - ytop_prev) // mos_pitch
                    ext_h = prev_ext_h + cur_bot_ext_h
                    if ext_h < valid_widths[-1] and ext_h not in valid_widths:
                        # make sure extension height is valid
                        ext_h = valid_widths[bisect.bisect_left(valid_widths, ext_h)]
                        cur_bot_ext_h = ext_h - prev_ext_h
                else:
                    # nmos/pmos at bottom row.  Need to check we can draw mirror image row.
                    tmp = self._place_mirror_or_sub(row_type, row_thres, lch_unit, mos_pitch,
                                                    ycur - ybot, ext_bot_info)
                    cur_bot_ext_h, self._bot_sub_extw = tmp

                ycur = ytop_prev + cur_bot_ext_h * mos_pitch

            # TODO: HERE
            if idx == self._num_rows - 1 and is_sub:
                # this is last row and it's the substrate, so no top tracks
                # we need to quantize row height, total height, and abut to top edge
                ytop = max(ycur + blk_height, ytop_prev + min_row_height, min_htot)
                ytop = -(-ytop // row_pitch) * row_pitch
                tot_height = -(-(ytop - ybot) // tot_height_pitch) * tot_height_pitch
                ytop = ybot + tot_height
                ycur = ytop - blk_height
                cur_bot_ext_h = (ycur - ytop_prev) // mos_pitch
                cur_top_ext_h = 0
            else:
                # move tracks if needed, then determine row top coordinate
                wire_groups = wire_tree.get_wire_groups((idx, 1))
                if wire_groups is None:
                    # no top tracks.  Move other tracks so they won't overlap this row.
                    yt = max((yintv[1] for yintv in top_conn_y))
                    wire_groups = wire_tree.get_wire_groups((idx, 1), get_next=True)
                    if wire_groups is not None:
                        for wg in wire_groups:
                            _, tr_idx, tr_w = wg.first_track
                            via_ext = self.grid.get_via_extensions(vm_layer, 1, tr_w,
                                                                   unit_mode=True)[0]
                            ymin = ycur + yt + vm_le_sp + via_ext
                            idx_targ = self.grid.find_next_track(hm_layer, ymin,
                                                                 tr_width=tr_w, half_track=True,
                                                                 mode=1, unit_mode=True)
                            if tr_idx < idx_targ:
                                wg.move_by(idx_targ - tr_idx, propagate=True)
                    # row top coordinate determined by block height.
                    ytop = ycur + blk_height
                else:
                    # move the top tracks so we can connect to them
                    for (yb, _), wg in zip(top_conn_y, wire_groups):
                        _, tr_idx, tr_w = wg.first_track
                        via_ext = self.grid.get_via_extensions(vm_layer, 1, tr_w, unit_mode=True)[0]
                        idx_targ = self.grid.find_next_track(hm_layer, ycur + yb + via_ext,
                                                             tr_width=tr_w, half_track=True,
                                                             mode=1, unit_mode=True)
                        if tr_idx < idx_targ:
                            wg.move_by(idx_targ - tr_idx, propagate=True)
                    # row top coordinate

                # determine top coordinate
                ytop = max(ycur + blk_height, ytop_prev + min_row_height)
                next_wires = self._get_next_wires(idx, wire_names, pinfo_list)
                cur_sp_top = tr_sp_top if idx == self._num_rows - 1 else 0
                tmp = self._compute_ytop(tr_next, ycur, ytop, hm_layer, top_conn_y, top_wires,
                                         last_track, conn_delta, vm_le_sp, row_pitch,
                                         tr_manager, next_wires, cur_sp_top)
                ytop, tr_next_new, last_track = tmp
                if idx != self._num_rows - 1:
                    cur_top_ext_h = (ytop - ycur - blk_height) // mos_pitch
                else:
                    # nmos/pmos at top row.
                    # compute distance of row from top edge
                    if row_orient == 'R0':
                        test_bcony = top_conn_y
                        test_bwires = top_wires
                    else:
                        test_bcony = bot_conn_y
                        test_bwires = bot_wires
                    ydelta, _ = self._place_with_num_tracks(tr_sp_top, hm_layer, test_bcony,
                                                            test_bwires, 0, conn_delta,
                                                            mos_pitch, tr_manager, [])
                    # update distance of row from top edge with previous ytop
                    ydelta = max(ydelta, ytop - ycur - blk_height)
                    # step 2: make sure ydelta can satisfy extension constraints.
                    tmp = self._place_mirror_or_sub(row_type, row_thres, lch_unit, mos_pitch,
                                                    ydelta, ext_top_info)
                    cur_top_ext_h, self._top_sub_extw = tmp
                    ydelta = cur_top_ext_h * mos_pitch
                    # TODO: Here, need to handle space between bottom and top connections
                    # step 3: compute row height given ycur and ydelta, round to row_pitch
                    ytop = max(ycur + blk_height + ydelta, ytop, min_htot)
                    ytop = -(-ytop // row_pitch) * row_pitch
                    # step 4: round to total height pitch
                    tot_height = -(-(ytop - ybot) // tot_height_pitch) * tot_height_pitch
                    ytop = ybot + tot_height
                    # step 4: update ycur
                    ycur = ytop - ydelta - blk_height
                    cur_bot_ext_h = (ycur - ytop_prev) // mos_pitch

            # recompute gate and drain/source track indices
            tmp = self._get_track_intervals(hm_layer, row_orient, row_info, ycur, ytop_prev,
                                            via_exty, ng, ngb, nds)
            g_intv, ds_intv, gb_intv, yt_vm_cur = tmp

            # record information
            row_info['g_intv'] = g_intv
            row_info['ds_intv'] = ds_intv
            row_info['gb_intv'] = gb_intv
            if prev_ext_info is None:
                ext_y = 0
            else:
                ext_y = row_y[-1][2]
            row_y.append((ytop_prev, ycur, ycur + blk_height, ytop))
            row_infos.append(row_info)
            ext_params_list.append((prev_ext_h + cur_bot_ext_h, ext_y))

            # update previous row information
            ytop_prev = ytop
            prev_ext_info = ext_top_info
            prev_ext_h = cur_top_ext_h

        return row_infos, ext_params_list, row_y

    def get_num_tracks(self, row_idx, tr_type):
        row_info = self._row_infos[row_idx]
        intv = row_info['%s_intv' % tr_type]
        return intv[1] - intv[0]

    def get_track_index(self, row_idx, tr_type, tr_idx):
        row_info = self._row_infos[row_idx]
        orient = self._row_orientations[row_idx]
        intv = row_info['%s_intv' % tr_type]
        ntr = intv[1] - intv[0]
        if tr_idx >= ntr:
            raise ValueError('tr_idx = %d >= %d' % (tr_idx, ntr))

        if orient == 'R0':
            return intv[0] + tr_idx
        else:
            return intv[1] - 1 - tr_idx

    def make_track_id(self, row_idx, tr_type, tr_idx, width=1, num=1, pitch=0.0):
        tid = self.get_track_index(row_idx, tr_type, tr_idx)
        hm_layer = self._tech_cls.get_dig_conn_layer() + 1
        return TrackID(hm_layer, tid, width=width, num=num, pitch=pitch)

    def get_ext_bot_info(self):
        return self._get_ext_info_row(0, 0)

    def get_ext_top_info(self):
        return self._get_ext_info_row(self._num_rows - 1, 1)

    def _get_ext_info_row(self, row_idx, ext_idx):
        intv = self._used_list[row_idx]
        return [ext_info[ext_idx] for ext_info in intv.values()]

    def get_left_edge_info(self):
        endl_list = []
        num_col = self._laygo_size[0]
        for intv in self._used_list:
            endl, endr = intv.get_end_info(num_col)
            endl_list.append(endl)

        return endl_list

    def get_right_edge_info(self):
        endr_list = []
        num_col = self._laygo_size[0]
        for intv in self._used_list:
            endl, endr = intv.get_end_info(num_col)
            endr_list.append(endr)

        return endr_list

    def _get_end_info_row(self, row_idx):
        num_col = self._laygo_size[0]
        endl, endr = self._used_list[row_idx].get_end_info(num_col)
        return endl, endr

    def set_laygo_size(self, num_col=None):
        if self._laygo_size is None:
            # compute total number of columns
            if num_col is None:
                if self._laygo_info.num_col is not None:
                    num_col = self._laygo_info.num_col
                else:
                    num_col = 0
                    for intv in self._used_list:
                        num_col = max(num_col, intv.get_end())

            self._laygo_info.set_num_col(num_col)
            self._laygo_size = num_col, self._num_rows

            top_layer = self._laygo_info.top_layer
            draw_boundaries = self._laygo_info.draw_boundaries

            width = self._laygo_info.tot_width
            height = self._row_y[-1][-1]
            if draw_boundaries:
                height += self._top_end_master.bound_box.height_unit
            bound_box = BBox(0, 0, width, height, self.grid.resolution, unit_mode=True)
            self.set_size_from_bound_box(top_layer, bound_box)
            self.add_cell_boundary(bound_box)

    def add_laygo_primitive(self, blk_type, loc=(0, 0), flip=False, nx=1, spx=0, **kwargs):
        # type: (str, Tuple[int, int], bool, int, int, **kwargs) -> Instance

        col_idx, row_idx = loc
        if row_idx < 0 or row_idx >= self._num_rows:
            raise ValueError('Cannot add primitive at row %d' % row_idx)

        row_info = self._row_infos[loc[1]]
        row_type = row_info['row_type']
        wblk = kwargs.pop('w', row_info['w_max'])

        col_width = self._laygo_info.col_width

        row_orient = self._row_orientations[row_idx]

        # make master
        options = self._row_kwargs[row_idx].copy()
        options.update(kwargs)
        params = dict(
            row_info=row_info,
            options=options,
        )
        if row_type == 'ntap' or row_type == 'ptap':
            master = self.new_template(params=params, temp_cls=LaygoSubstrate)
        else:
            params['blk_type'] = blk_type
            params['w'] = wblk
            master = self.new_template(params=params, temp_cls=LaygoPrimitive)

        num_col = master.laygo_size[0]
        intv = self._used_list[row_idx]
        inst_endl = master.get_left_edge_info()
        inst_endr = master.get_right_edge_info()
        ext_info = master.get_ext_bot_info(), master.get_ext_top_info()
        if row_orient == 'MX':
            ext_info = ext_info[1], ext_info[0]
        if flip:
            inst_endl, inst_endr = inst_endr, inst_endl
        for inst_num in range(nx):
            intv_offset = col_idx + spx * inst_num
            inst_intv = intv_offset, intv_offset + num_col
            if not intv.add(inst_intv, ext_info, inst_endl, inst_endr):
                raise ValueError('Cannot add primitive on row %d, '
                                 'column [%d, %d).' % (row_idx, inst_intv[0], inst_intv[1]))

        x0 = self._laygo_info.col_to_coord(col_idx, 's', unit_mode=True)
        if flip:
            x0 += master.bound_box.width_unit

        _, ycur, ytop, _ = self._row_y[row_idx]
        if row_orient == 'R0':
            y0 = self._row_y[row_idx][1]
            orient = 'MY' if flip else 'R0'
        else:
            y0 = self._row_y[row_idx][2]
            orient = 'R180' if flip else 'MX'

        # convert horizontal pitch to resolution units
        spx *= col_width

        inst_name = 'XR%dC%d' % (row_idx, col_idx)
        return self.add_instance(master, inst_name=inst_name, loc=(x0, y0), orient=orient,
                                 nx=nx, spx=spx, unit_mode=True)

    def fill_space(self):
        if self._laygo_size is None:
            raise ValueError('laygo_size must be set before filling spaces.')

        num_col = self._laygo_size[0]
        # add space blocks
        total_intv = (0, num_col)
        for row_idx, (intv, endl_info, endr_info) in \
                enumerate(zip(self._used_list, self._endl_infos, self._endr_infos)):
            for (start, end), end_info in zip(*intv.get_complement(total_intv, endl_info,
                                                                   endr_info)):
                self.add_laygo_space(end_info, num_blk=end - start, loc=(start, row_idx))

        # draw extensions
        self._ext_edge_infos = []
        laygo_info = self._laygo_info
        tech_cls = laygo_info.tech_cls
        for bot_ridx in range(0, self._num_rows - 1):
            w, yext = self._ext_params[bot_ridx + 1]
            bot_ext_list = self._get_ext_info_row(bot_ridx, 1)
            top_ext_list = self._get_ext_info_row(bot_ridx + 1, 0)
            self._ext_edge_infos.extend(tech_cls.draw_extensions(self, laygo_info, w, yext,
                                                                 bot_ext_list, top_ext_list))

        # draw boundaries and return guard ring supplies in boundary cells
        return self._draw_boundary_cells()

    def add_laygo_space(self, adj_end_info, num_blk=1, loc=(0, 0), **kwargs):
        col_idx, row_idx = loc
        row_info = self._row_infos[row_idx]
        row_y = self._row_y[row_idx]
        row_orient = self._row_orientations[row_idx]
        intv = self._used_list[row_idx]

        params = dict(
            row_info=row_info,
            num_blk=num_blk,
            left_blk_info=adj_end_info[0],
            right_blk_info=adj_end_info[1],
        )
        params.update(kwargs)
        inst_name = 'XR%dC%d' % (row_idx, col_idx)
        master = self.new_template(params=params, temp_cls=LaygoSpace)

        # update used interval
        endl = master.get_left_edge_info()
        endr = master.get_right_edge_info()
        ext_info = master.get_ext_bot_info(), master.get_ext_top_info()
        if row_orient == 'MX':
            ext_info = ext_info[1], ext_info[0]

        inst_intv = (col_idx, col_idx + num_blk)
        if not intv.add(inst_intv, ext_info, endl, endr):
            raise ValueError('Cannot add space on row %d, '
                             'column [%d, %d)' % (row_idx, inst_intv[0], inst_intv[1]))

        x0 = self._laygo_info.col_to_coord(col_idx, 's', unit_mode=True)
        y0 = row_y[1] if row_orient == 'R0' else row_y[2]
        self.add_instance(master, inst_name=inst_name, loc=(x0, y0), orient=row_orient,
                          unit_mode=True)

    def _get_row_edge_infos(self):
        top_layer = self._laygo_info.top_layer
        guard_ring_nf = self._laygo_info.guard_ring_nf

        row_edge_infos = []
        for ridx, (orient, ytuple, rinfo) in enumerate(zip(self._row_orientations,
                                                           self._row_y, self._row_infos)):
            if orient == 'R0':
                y = ytuple[1]
            else:
                y = ytuple[2]

            row_edge_params = dict(
                top_layer=top_layer,
                guard_ring_nf=guard_ring_nf,
                row_info=rinfo,
                is_laygo=True,
            )
            row_edge_infos.append((y, orient, row_edge_params))

        return row_edge_infos

    def _draw_boundary_cells(self):
        if self._laygo_info.draw_boundaries:
            if self._laygo_size is None:
                raise ValueError('laygo_size must be set before drawing boundaries.')

            end_mode = self._laygo_info.end_mode
            emargin_l, emargin_r = self._laygo_info.edge_margins
            tcls = self._tech_cls

            xr = self.bound_box.right_unit

            left_end = (end_mode & 4) != 0
            right_end = (end_mode & 8) != 0

            edge_infos = []
            # compute extension edge information
            for y, orient, edge_params in self._ext_edge_infos:
                tmp_copy = edge_params.copy()
                if orient == 'R0':
                    x = emargin_l
                    tmp_copy['is_end'] = left_end
                else:
                    x = xr - emargin_r
                    tmp_copy['is_end'] = right_end
                edge_infos.append((x, y, orient, tmp_copy))

            # compute row edge information
            row_edge_infos = self._get_row_edge_infos()
            for ridx, (y, orient, re_params) in enumerate(row_edge_infos):
                cur_row_info = re_params['row_info']
                test_blk_info = tcls.get_laygo_blk_info('fg2d', cur_row_info['w_max'], cur_row_info)

                endl, endr = self._get_end_info_row(ridx)
                for x, is_end, flip_lr, end_info in ((emargin_l, left_end, False, endl),
                                                     (xr - emargin_r, right_end, True, endr)):
                    edge_params = re_params.copy()
                    del edge_params['row_info']
                    edge_params['is_end'] = is_end
                    edge_params['name_id'] = cur_row_info['row_name_id']
                    edge_params['layout_info'] = test_blk_info['layout_info']
                    edge_params['adj_blk_info'] = end_info
                    if flip_lr:
                        eorient = 'MY' if orient == 'R0' else 'R180'
                    else:
                        eorient = orient
                    edge_infos.append((x, y, eorient, edge_params))

            yt = self.bound_box.top_unit
            vdd_warrs, vss_warrs = tcls.draw_boundaries(self, self._laygo_info, self._laygo_size[0],
                                                        yt, self._bot_end_master,
                                                        self._top_end_master, edge_infos)

            return vdd_warrs, vss_warrs

        return [], []
