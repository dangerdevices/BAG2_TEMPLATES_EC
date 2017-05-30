# -*- coding: utf-8 -*-
########################################################################################################################
#
# Copyright (c) 2014, Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following
#   disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
#    following disclaimer in the documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
########################################################################################################################

"""This module defines AmplifierBase, a base template class for Amplifier-like layout topologies."""
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
# noinspection PyUnresolvedReferences,PyCompatibility
from builtins import *

import abc
from itertools import chain
from typing import List, Union, Optional, Dict, Any, Set, Tuple

from bag.math import lcm
from bag.util.interval import IntervalSet
from bag.util.search import BinaryIterator
from bag.layout.template import TemplateBase, TemplateDB
from bag.layout.routing import TrackID, WireArray, RoutingGrid
from bag.layout.util import BBox
from bag.layout.objects import Instance
from future.utils import with_metaclass

from .analog_mos.core import MOSTech
from .analog_mos.mos import AnalogMOSBase, AnalogMOSExt
from .analog_mos.substrate import AnalogSubstrate
from .analog_mos.edge import AnalogEdge, AnalogEndRow
from .analog_mos.conn import AnalogMOSConn, AnalogMOSDecap, AnalogMOSDummy, AnalogSubstrateConn


class AnalogBaseInfo(object):
    """A class that calculates informations to assist in AnalogBase layout calculations.

    Parameters
    ----------
    grid : RoutingGrid
        the RoutingGrid object.
    lch : float
        the channel length of AnalogBase, in meters.
    guard_ring_nf : int
        guard ring width in number of fingers.  0 to disable.
    top_layer : Optional[int]
        the top level routing layer ID.
    end_mode : int
        right/left/top/bottom end mode flag.  This is a 4-bit integer.  If bit 0 (LSB) is 1, then
        we assume there are no blocks abutting the bottom.  If bit 1 is 1, we assume there are no
        blocks abutting the top.  bit 2 and bit 3 (MSB) corresponds to left and right, respectively.
        The default value is 15, which means we assume this AnalogBase is surrounded by empty spaces.
    min_fg_sep : int
        minimum number of separation fingers.
    """

    def __init__(self, grid, lch, guard_ring_nf, top_layer=None, end_mode=15, min_fg_sep=0):
        # type: (RoutingGrid, float, int, Optional[int], int, int) -> None
        tech_params = grid.tech_info.tech_params
        self._tech_cls = tech_params['layout']['mos_tech_class']  # type: MOSTech

        # get technology parameters
        self.min_fg_sep = max(min_fg_sep, tech_params['layout']['analog_base']['min_fg_sep'])
        self.mconn_diff = tech_params['layout']['analog_base']['mconn_diff_mode']
        self.float_dummy = tech_params['layout']['analog_base']['floating_dummy']

        # update RoutingGrid
        lch_unit = int(round(lch / grid.layout_unit / grid.resolution))
        self.grid = grid
        self._lch_unit = lch_unit
        self.mconn_port_layer = self._tech_cls.get_mos_conn_layer()
        self.dum_port_layer = self._tech_cls.get_dum_conn_layer()
        vm_space, vm_width = self._tech_cls.get_mos_conn_track_info(lch_unit)
        dum_space, dum_width = self._tech_cls.get_dum_conn_track_info(lch_unit)
        self.grid.add_new_layer(self.mconn_port_layer, vm_space, vm_width, 'y', override=True, unit_mode=True)
        self.grid.add_new_layer(self.dum_port_layer, dum_space, dum_width, 'y', override=True, unit_mode=True)
        self.grid.update_block_pitch()

        # initialize parameters
        left_end = (end_mode & 4) != 0
        self.guard_ring_nf = guard_ring_nf
        if top_layer is None:
            top_layer = self.mconn_port_layer + 1
        self.top_layer = top_layer
        self.end_mode = end_mode
        self.min_fg_decap = self._tech_cls.get_min_fg_decap(lch_unit)
        self.num_fg_per_sd = self._tech_cls.get_num_fingers_per_sd(lch_unit)
        self._sd_pitch_unit = self._tech_cls.get_sd_pitch(lch_unit)
        self._sd_xc_unit = self._tech_cls.get_left_sd_xc(self.grid, lch_unit, guard_ring_nf, top_layer, left_end)

    @property
    def vertical_pitch_unit(self):
        blk_pitch = self.grid.get_block_size(self.top_layer, unit_mode=True)[1]
        return lcm([blk_pitch, self._tech_cls.get_mos_pitch(unit_mode=True)])

    @property
    def sd_pitch(self):
        return self._sd_pitch_unit * self.grid.resolution

    @property
    def sd_pitch_unit(self):
        return self._sd_pitch_unit

    @property
    def sd_xc(self):
        return self._sd_xc_unit * self.grid.resolution

    @property
    def sd_xc_unit(self):
        return self._sd_xc_unit

    def get_total_width(self, fg_tot):
        # type: (int) -> int
        """Returns the width of the AnalogMosBase in number of source/drain tracks.

        Parameters
        ----------
        fg_tot : int
            number of fingers.

        Returns
        -------
        mos_width : int
            the AnalogMosBase width in number of source/drain tracks.
        """
        left_end = (self.end_mode & 4) != 0
        right_end = (self.end_mode & 8) != 0
        left_width = self._tech_cls.get_left_sd_xc(self.grid, self._lch_unit, self.guard_ring_nf,
                                                   self.top_layer, left_end)
        right_width = self._tech_cls.get_left_sd_xc(self.grid, self._lch_unit, self.guard_ring_nf,
                                                    self.top_layer, right_end)
        tot_width = left_width + right_width + fg_tot * self._sd_pitch_unit
        return tot_width // self._sd_pitch_unit

    def round_up_fg_tot(self, fg_min):
        # type: (int) -> int
        """Round up number of fingers so the resulting AnalogBase has the correct width quantization.

        Parameters
        ----------
        fg_min : int
            minimum number of fingers per row.

        Returns
        -------
        fg_tot : int
            number of fingers in a row.  This number is guaranteed to be greater than fg_min, and an
            AnalogBase drawn with this many fingers will have the correct width quantization with
            respect to the specified top level routing layer.
        """
        blk_w = self.grid.get_block_size(self.top_layer, unit_mode=True)[0]
        arr_box_w = fg_min * self._sd_pitch_unit
        tot_w = -(-arr_box_w // blk_w) * blk_w
        return tot_w // self._sd_pitch_unit

    def coord_to_col(self, coord, unit_mode=False, mode=0):
        """Convert the given X coordinate to transistor column index.
        
        Find the left source/drain index closest to the given coordinate.

        Parameters
        ----------
        coord : Union[float, int]
            the X coordinate.
        unit_mode : bool
            True to if coordinate is given in resolution units.
        mode : int
            rounding mode.
        Returns
        -------
        col_idx : int
            the left source/drain index closest to the given coordinate.
        """
        res = self.grid.resolution
        if not unit_mode:
            coord = int(round(coord / res))

        diff = coord - self._sd_xc_unit
        pitch = self._sd_pitch_unit
        if mode == 0:
            q = (diff + pitch // 2) // pitch
        elif mode < 0:
            q = diff // pitch
        else:
            q = -(-diff // pitch)

        return q

    def col_to_coord(self, col_idx, unit_mode=False):
        """Convert the given transistor column index to X coordinate.

        Parameters
        ----------
        col_idx : int
            the transistor index.  0 is left-most transistor.
        unit_mode : bool
            True to return coordinate in resolution units.

        Returns
        -------
        xcoord : float
            X coordinate of the left source/drain center of the given transistor.
        """
        coord = self._sd_xc_unit + col_idx * self._sd_pitch_unit
        if unit_mode:
            return coord
        return coord * self.grid.resolution

    def track_to_col_intv(self, layer_id, tr_idx, width=1):
        # type: (int, Union[float, int], int) -> Tuple[int, int]
        """Returns the smallest column interval that covers the given vertical track."""
        lower, upper = self.grid.get_wire_bounds(layer_id, tr_idx, width=width, unit_mode=True)

        lower_col_idx = (lower - self._sd_xc_unit) // self._sd_pitch_unit  # type: int
        upper_col_idx = -(-(upper - self._sd_xc_unit) // self._sd_pitch_unit)  # type: int
        return lower_col_idx, upper_col_idx

    def get_center_tracks(self, layer_id, num_tracks, col_intv, width=1, space=0):
        # type: (int, int, Tuple[int, int], int, Union[float, int]) -> float
        """Return tracks that center on the given column interval.

        Parameters
        ----------
        layer_id : int
            the vertical layer ID.
        num_tracks : int
            number of tracks
        col_intv : Tuple[int, int]
            the column interval.
        width : int
            width of each track.
        space : Union[float, int]
            space between tracks.

        Returns
        -------
        track_id : float
            leftmost track ID of the center tracks.
        """
        x0_unit = self.col_to_coord(col_intv[0], unit_mode=True)
        x1_unit = self.col_to_coord(col_intv[1], unit_mode=True)
        # find track number with coordinate strictly larger than x0
        t_start = self.grid.find_next_track(layer_id, x0_unit, half_track=True, mode=1, unit_mode=True)
        t_stop = self.grid.find_next_track(layer_id, x1_unit, half_track=True, mode=-1, unit_mode=True)
        ntracks = int(t_stop - t_start + 1)
        tot_tracks = num_tracks * width + (num_tracks - 1) * space
        if ntracks < tot_tracks:
            raise ValueError('There are only %d tracks in column interval [%d, %d)'
                             % (ntracks, col_intv[0], col_intv[1]))

        ans = t_start + (ntracks - tot_tracks + width - 1) / 2
        return ans

    def num_tracks_to_fingers(self, layer_id, num_tracks, col_idx, even=True, fg_margin=0):
        """Returns the minimum number of fingers needed to span given number of tracks.

        Returns the smallest N such that the transistor interval [col_idx, col_idx + N)
        contains num_tracks wires on routing layer layer_id.

        Parameters
        ----------
        layer_id : int
            the vertical layer ID.
        num_tracks : int
            number of tracks
        col_idx : int
            the starting column index.
        even : bool
            True to return even integers.
        fg_margin : int
            Ad this many fingers on both sides of tracks to act as margin.

        Returns
        -------
        min_fg : int
            minimum number of fingers needed to span the given number of tracks.
        """
        x0 = self.col_to_coord(col_idx, unit_mode=True)
        x1 = self.col_to_coord(col_idx + fg_margin, unit_mode=True)
        # find track number with coordinate strictly larger than x0
        t_start = self.grid.find_next_track(layer_id, x1, half_track=True, mode=1, unit_mode=True)
        # find coordinate of last track
        xlast = self.grid.track_to_coord(layer_id, t_start + num_tracks - 1, unit_mode=True)
        xlast += self.grid.get_track_width(layer_id, 1, unit_mode=True) // 2

        # divide by source/drain pitch
        q, r = divmod(xlast - x0, self._sd_pitch_unit)
        if r > 0:
            q += 1
        q += fg_margin
        if even and q % 2 == 1:
            q += 1
        return q


# noinspection PyAbstractClass
class AnalogBase(with_metaclass(abc.ABCMeta, TemplateBase)):
    """The amplifier abstract template class

    An amplifier template consists of rows of pmos or nmos capped by substrate contacts.
    drain/source connections are mostly vertical, and gate connections are horizontal.  extension
    rows may be inserted to allow more space for gate/output connections.

    each row starts and ends with dummy transistors, and two transistors are always separated
    by separators.  Currently source sharing (e.g. diff pair) and inter-digitation are not
    supported.  All transistors have the same channel length.

    To use this class, draw_base() must be the first function called.

    Parameters
    ----------
    temp_db : TemplateDB
        the template database.
    lib_name : str
        the layout library name.
    params : Dict[str, Any]
        the parameter values.
    used_names : Set[str]
        a set of already used cell names.
    **kwargs
        dictionary of optional parameters.  See documentation of
        :class:`bag.layout.template.TemplateBase` for details.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        super(AnalogBase, self).__init__(temp_db, lib_name, params, used_names, **kwargs)

        tech_params = self.grid.tech_info.tech_params
        self._tech_cls = tech_params['layout']['mos_tech_class']  # type: MOSTech

        # initialize parameters
        # layout information parameters
        self._lch = None
        self._w_list = None
        self._orient_list = None
        self._fg_tot = None
        self._sd_yc_list = None
        self._mos_kwargs_list = None
        self._layout_info = None
        self._dum_conn_pitch = self._tech_cls.get_dum_conn_pitch()
        if self._dum_conn_pitch != 1 and self._dum_conn_pitch != 2:
            raise ValueError('Current only support dum_conn_pitch = 1 or 2, but it is %d' % self._dum_conn_pitch)

        # transistor usage/automatic dummy parameters
        self._n_intvs = None  # type: List[IntervalSet]
        self._p_intvs = None  # type: List[IntervalSet]
        self._capn_intvs = None
        self._capp_intvs = None
        self._capp_wires = {-1: [], 1: []}
        self._capn_wires = {-1: [], 1: []}

        # track calculation parameters
        self._ridx_lookup = None
        self._gtr_intv = None
        self._dstr_intv = None

        # substrate parameters
        self._ntap_list = None
        self._ptap_list = None
        self._ptap_exports = None
        self._ntap_exports = None
        self._gr_vdd_warrs = None
        self._gr_vss_warrs = None

    @classmethod
    def get_mos_conn_layer(cls, tech_info):
        tech_cls = tech_info.tech_params['layout']['mos_tech_class']
        return tech_cls.get_mos_conn_layer()

    @property
    def layout_info(self):
        # type: () -> AnalogBaseInfo
        return self._layout_info

    @property
    def num_fg_per_sd(self):
        return self._layout_info.num_fg_per_sd

    @property
    def min_fg_sep(self):
        """Returns the minimum number of separator fingers.
        """
        return self._layout_info.min_fg_sep

    @property
    def min_fg_decap(self):
        """Returns the minimum number of decap fingers.
        """
        return self._layout_info.min_fg_decap

    @property
    def sd_pitch(self):
        """Returns the transistor source/drain pitch."""
        return self._layout_info.sd_pitch

    @property
    def sd_pitch_unit(self):
        """Returns the transistor source/drain pitch."""
        return self._layout_info.sd_pitch_unit

    @property
    def mos_conn_layer(self):
        """Returns the MOSFET connection layer ID."""
        return self._layout_info.mconn_port_layer

    @property
    def dum_conn_layer(self):
        """REturns the dummy connection layer ID."""
        return self._layout_info.dum_port_layer

    @property
    def min_fg_sep(self):
        """Returns the minimum number of separator fingers."""
        return self._layout_info.min_fg_sep

    @property
    def mconn_diff_mode(self):
        """Returns True if AnalogMosConn supports diffpair mode."""
        return self._layout_info.mconn_diff

    @property
    def floating_dummy(self):
        """Returns True if floating dummy connection is OK."""
        return self._layout_info.float_dummy

    def _find_row_index(self, mos_type, row_idx):
        ridx_list = self._ridx_lookup[mos_type]
        if row_idx < 0 or row_idx >= len(ridx_list):
            # error checking
            raise ValueError('%s row with index = %d not found' % (mos_type, row_idx))
        return ridx_list[row_idx]

    def get_num_tracks(self, mos_type, row_idx, tr_type):
        """Get number of tracks of the given type on the given row.

        Parameters
        ----------
        mos_type : string
            the row type, one of 'nch', 'pch', 'ntap', or 'ptap'
        row_idx : int
            the row index.  0 is the bottom-most row.
        tr_type : string
            the type of the track.  Either 'g' or 'ds'.

        Returns
        -------
        num_tracks : int
            number of tracks.
        """
        row_idx = self._find_row_index(mos_type, row_idx)
        if tr_type == 'g':
            tr_intv = self._gtr_intv[row_idx]
        else:
            tr_intv = self._dstr_intv[row_idx]

        return tr_intv[1] - tr_intv[0]

    def get_track_index(self, mos_type, row_idx, tr_type, tr_idx):
        """Convert relative track index to absolute track index.

        Parameters
        ----------
        mos_type : string
            the row type, one of 'nch', 'pch', 'ntap', or 'ptap'.
        row_idx : int
            the center row index.  0 is the bottom-most row.
        tr_type : str
            the type of the track.  Either 'g' or 'ds'.
        tr_idx : float
            the relative track index.

        Returns
        -------
        abs_tr_idx : float
            the absolute track index.
        """
        row_idx = self._find_row_index(mos_type, row_idx)
        if tr_type == 'g':
            tr_intv = self._gtr_intv[row_idx]
        else:
            tr_intv = self._dstr_intv[row_idx]

        # error checking
        ntr = tr_intv[1] - tr_intv[0]
        if tr_idx >= ntr:
            raise ValueError('track_index %d out of bounds: [0, %d)' % (tr_idx, ntr))

        if self._orient_list[row_idx] == 'R0':
            return tr_intv[0] + tr_idx
        else:
            return tr_intv[1] - 1 - tr_idx

    def make_track_id(self, mos_type, row_idx, tr_type, tr_idx, width=1,
                      num=1, pitch=0.0):
        """Make TrackID representing the given relative index

        Parameters
        ----------
        mos_type : string
            the row type, one of 'nch', 'pch', 'ntap', or 'ptap'.
        row_idx : int
            the center row index.  0 is the bottom-most row.
        tr_type : str
            the type of the track.  Either 'g' or 'ds'.
        tr_idx : float
            the relative track index.
        width : int
            track width in number of tracks.
        num : int
            number of tracks in this array.
        pitch : float
            pitch between adjacent tracks, in number of track pitches.

        Returns
        -------
        tr_id : :class:`~bag.layout.routing.TrackID`
            TrackID representing the specified track.
        """
        tid = self.get_track_index(mos_type, row_idx, tr_type, tr_idx)
        return TrackID(self.mos_conn_layer + 1, tid, width=width, num=num, pitch=pitch)

    def connect_to_substrate(self, sub_type, warr_list, inner=False, both=False):
        """Connect the given transistor wires to substrate.
        
        Parameters
        ----------
        sub_type : string
            substrate type.  Either 'ptap' or 'ntap'.
        warr_list : :class:`~bag.layout.routing.WireArray` or Iterable[:class:`~bag.layout.routing.WireArray`]
            list of WireArrays to connect to supply.
        inner : bool
            True to connect to inner substrate.
        both : bool
            True to connect to both substrates
        """
        if isinstance(warr_list, WireArray):
            warr_list = [warr_list]
        wire_yb, wire_yt = None, None
        port_name = 'VDD' if sub_type == 'ntap' else 'VSS'

        if both:
            # set inner to True if both is True
            inner = True

        # get wire upper/lower Y coordinate and record used supply tracks
        sub_port_id_list = [tid for warr in warr_list for tid in warr.track_id]
        if sub_type == 'ptap':
            if inner:
                if len(self._ptap_list) != 2:
                    raise ValueError('Inner substrate does not exist.')
                port = self._ptap_list[1].get_port(port_name)
                self._ptap_exports[1].update(sub_port_id_list)
                wire_yt = port.get_bounding_box(self.grid, self.mos_conn_layer).top
            if not inner or both:
                port = self._ptap_list[0].get_port(port_name)
                self._ptap_exports[0].update(sub_port_id_list)
                wire_yb = port.get_bounding_box(self.grid, self.mos_conn_layer).bottom
        elif sub_type == 'ntap':
            if inner:
                if len(self._ntap_list) != 2:
                    raise ValueError('Inner substrate does not exist.')
                port = self._ntap_list[0].get_port(port_name)
                self._ntap_exports[0].update(sub_port_id_list)
                wire_yb = port.get_bounding_box(self.grid, self.mos_conn_layer).bottom
            if not inner or both:
                port = self._ntap_list[-1].get_port(port_name)
                self._ntap_exports[-1].update(sub_port_id_list)
                wire_yt = port.get_bounding_box(self.grid, self.mos_conn_layer).top
        else:
            raise ValueError('Invalid substrate type: %s' % sub_type)

        self.connect_wires(warr_list, lower=wire_yb, upper=wire_yt)

    def _draw_dummy_sep_conn(self, mos_type, row_idx, start, stop, dum_htr_list):
        """Draw dummy/separator connection.

        Parameters
        ----------
        mos_type : string
            the row type, one of 'nch', 'pch', 'ntap', or 'ptap'.
        row_idx : int
            the center row index.  0 is the bottom-most row.
        start : int
            starting column index, inclusive.  0 is the left-most transistor.
        stop : int
            stopping column index, exclusive.
        dum_htr_list : List[int]
            list of dummy half-track indices to export.

        Returns
        -------
        use_htr : List[int]
            Used dummy half tracks.
        yb : int
            dummy port bottom Y coordinate, in resolution units.
        yt : int
            dummy port top Y coordinate, in resolution units.
        """
        # get orientation, width, and source/drain center
        ridx = self._ridx_lookup[mos_type][row_idx]
        orient = self._orient_list[ridx]
        w = self._w_list[ridx]
        xc, yc = self._layout_info.sd_xc_unit, self._sd_yc_list[ridx]
        xc += start * self.sd_pitch_unit
        fg = stop - start

        layout_info = self._layout_info
        dum_layer = self.dum_conn_layer
        xl = layout_info.col_to_coord(start, unit_mode=True)
        xr = layout_info.col_to_coord(stop, unit_mode=True)
        htr0 = int(1 + 2 * self.grid.coord_to_track(dum_layer, xl, unit_mode=True))
        htr1 = int(1 + 2 * self.grid.coord_to_track(dum_layer, xr, unit_mode=True))

        edge_mode = 0
        if start > 0:
            htr0 += 1
        else:
            edge_mode += 1
        if stop == self._fg_tot:
            htr1 += 1
            edge_mode += 2

        # get track indices to export
        used_htr = []
        dum_tr_list = []
        tr_offset = self.grid.coord_to_track(dum_layer, xc, unit_mode=True) + 0.5
        for v in dum_htr_list:
            if v >= htr1:
                break
            elif v >= htr0:
                used_htr.append(v)
                dum_tr_list.append((v - 1) / 2 - tr_offset)

        # setup parameter list
        loc = xc, yc
        params = dict(
            lch=self._lch,
            w=w,
            fg=fg,
            edge_mode=edge_mode,
            gate_tracks=dum_tr_list,
        )
        conn_master = self.new_template(params=params, temp_cls=AnalogMOSDummy)
        conn_inst = self.add_instance(conn_master, loc=loc, orient=orient, unit_mode=True)

        warr = conn_inst.get_port().get_pins(dum_layer)[0]
        res = self.grid.resolution
        yb = int(round(warr.lower / res))
        yt = int(round(warr.upper / res))
        return used_htr, yb, yt

    def mos_conn_track_used(self, tidx, margin=0):
        col_start, col_stop = self.layout_info.track_to_col_intv(self.mos_conn_layer, tidx)
        col_intv = col_start - margin, col_stop + margin
        for intv_set in chain(self._p_intvs, self._n_intvs):
            if intv_set.has_overlap(col_intv):
                return True
        return False

    def draw_mos_decap(self, mos_type, row_idx, col_idx, fg, gate_ext_mode, export_gate=False,
                       inner=False, **kwargs):
        """Draw decap connection."""
        # mark transistors as connected
        val = -1 if inner else 1
        if mos_type == 'pch':
            val *= -1
            intv_set = self._p_intvs[row_idx]
            cap_intv_set = self._capp_intvs[row_idx]
            wires_dict = self._capp_wires
        else:
            intv_set = self._n_intvs[row_idx]
            cap_intv_set = self._capn_intvs[row_idx]
            wires_dict = self._capn_wires

        intv = col_idx, col_idx + fg
        if not export_gate:
            # add to cap_intv_set, since we can route dummies over it
            if intv_set.has_overlap(intv) or not cap_intv_set.add(intv, val=val):
                msg = 'Cannot connect %s row %d [%d, %d); some are already connected.'
                raise ValueError(msg % (mos_type, row_idx, intv[0], intv[1]))
        else:
            # add to normal intv set.
            if cap_intv_set.has_overlap(intv) or not intv_set.add(intv, val=val):
                msg = 'Cannot connect %s row %d [%d, %d); some are already connected.'
                raise ValueError(msg % (mos_type, row_idx, intv[0], intv[1]))

        ridx = self._ridx_lookup[mos_type][row_idx]
        orient = self._orient_list[ridx]
        w = self._w_list[ridx]
        xc, yc = self._layout_info.sd_xc_unit, self._sd_yc_list[ridx]
        xc += col_idx * self.sd_pitch_unit

        loc = xc, yc
        conn_params = dict(
            lch=self._lch,
            w=w,
            fg=fg,
            gate_ext_mode=gate_ext_mode,
            export_gate=export_gate,
        )
        conn_params.update(kwargs)

        conn_master = self.new_template(params=conn_params, temp_cls=AnalogMOSDecap)
        inst = self.add_instance(conn_master, loc=loc, orient=orient, unit_mode=True)
        wires_dict[val].extend(inst.get_all_port_pins('supply'))
        if export_gate:
            return {'g': inst.get_all_port_pins('g')[0]}
        else:
            return {}

    def draw_mos_conn(self, mos_type, row_idx, col_idx, fg, sdir, ddir, **kwargs):
        """Draw transistor connection.

        Parameters
        ----------
        mos_type : string
            the row type, one of 'nch', 'pch', 'ntap', or 'ptap'.
        row_idx : int
            the center row index.  0 is the bottom-most row.
        col_idx : int
            the left-most transistor index.  0 is the left-most transistor.
        fg : int
            number of fingers.
        sdir : int
            source connection direction.  0 for down, 1 for middle, 2 for up.
        ddir : int
            drain connection direction.  0 for down, 1 for middle, 2 for up.
        **kwargs :
            optional arguments for AnalogMosConn.
        Returns
        -------
        ports : dict[str, :class:`~bag.layout.routing.WireArray`]
            a dictionary of ports as WireArrays.  The keys are 'g', 'd', and 's'.
        """
        # mark transistors as connected
        if mos_type == 'pch':
            intv_set = self._p_intvs[row_idx]
            cap_intv_set = self._capp_intvs[row_idx]
        else:
            intv_set = self._n_intvs[row_idx]
            cap_intv_set = self._capn_intvs[row_idx]

        intv = col_idx, col_idx + fg
        if cap_intv_set.has_overlap(intv) or not intv_set.add(intv):
            msg = 'Cannot connect %s row %d [%d, %d); some are already connected.'
            raise ValueError(msg % (mos_type, row_idx, intv[0], intv[1]))

        sd_pitch = self.sd_pitch_unit
        ridx = self._ridx_lookup[mos_type][row_idx]
        orient = self._orient_list[ridx]
        mos_kwargs = self._mos_kwargs_list[ridx]
        w = self._w_list[ridx]
        xc, yc = self._layout_info.sd_xc_unit, self._sd_yc_list[ridx]
        xc += col_idx * sd_pitch

        if orient == 'MX':
            # flip source/drain directions
            sdir = 2 - sdir
            ddir = 2 - ddir

        loc = xc, yc
        conn_params = dict(
            lch=self._lch,
            w=w,
            fg=fg,
            sdir=sdir,
            ddir=ddir,
            options=mos_kwargs,
        )
        conn_params.update(kwargs)

        conn_master = self.new_template(params=conn_params, temp_cls=AnalogMOSConn)
        conn_inst = self.add_instance(conn_master, loc=loc, orient=orient, unit_mode=True)

        return {key: conn_inst.get_port(key).get_pins(self.mos_conn_layer)[0]
                for key in conn_inst.port_names_iter()}

    def _make_masters(self, mos_type, lch, bot_sub_w, bot_sub_end, top_sub_w, top_sub_end, w_list, th_list,
                      g_tracks, ds_tracks, orientations, mos_kwargs, row_offset):

        # error checking + set default values.
        num_tran = len(w_list)
        if num_tran != len(th_list):
            raise ValueError('transistor type %s width/threshold list length mismatch.' % mos_type)
        if not g_tracks:
            g_tracks = [1] * num_tran
        elif num_tran != len(g_tracks):
            raise ValueError('transistor type %s width/g_tracks list length mismatch.' % mos_type)
        if not ds_tracks:
            ds_tracks = [1] * num_tran
        elif num_tran != len(ds_tracks):
            raise ValueError('transistor type %s width/ds_tracks list length mismatch.' % mos_type)
        if not orientations:
            default_orient = 'R0' if mos_type == 'nch' else 'MX'
            orientations = [default_orient] * num_tran
        elif num_tran != len(orientations):
            raise ValueError('transistor type %s width/orientations list length mismatch.' % mos_type)
        if not mos_kwargs:
            mos_kwargs = [{}] * num_tran
        elif num_tran != len(mos_kwargs):
            raise ValueError('transistor type %s width/kwargs list length mismatch.' % mos_type)

        if not w_list:
            # do nothing
            return [], [], [], []

        sub_type = 'ptap' if mos_type == 'nch' else 'ntap'
        master_list = []
        track_spec_list = []
        w_list_final = []
        # make bottom substrate
        if bot_sub_w > 0:
            sub_params = dict(
                lch=lch,
                w=bot_sub_w,
                sub_type=sub_type,
                threshold=th_list[0],
                end_mode=bot_sub_end,
                top_layer=None,
            )
            master_list.append(self.new_template(params=sub_params, temp_cls=AnalogSubstrate))
            track_spec_list.append(('R0', -1, -1))
            self._ridx_lookup[sub_type].append(row_offset)
            row_offset += 1
            w_list_final.append(bot_sub_w)

        # make transistors
        for w, th, gtr, dstr, orient, mkwargs in zip(w_list, th_list, g_tracks, ds_tracks, orientations, mos_kwargs):
            if gtr < 0 or dstr < 0:
                raise ValueError('number of gate/drain/source tracks cannot be negative.')
            params = dict(
                lch=lch,
                w=w,
                mos_type=mos_type,
                threshold=th,
                options=mkwargs,
            )
            master_list.append(self.new_template(params=params, temp_cls=AnalogMOSBase))
            track_spec_list.append((orient, gtr, dstr))
            self._ridx_lookup[mos_type].append(row_offset)
            row_offset += 1
            w_list_final.append(w)

        # make top substrate
        if top_sub_w > 0:
            sub_params = dict(
                lch=lch,
                w=top_sub_w,
                sub_type=sub_type,
                threshold=th_list[-1],
                end_mode=top_sub_end,
                top_layer=None,
            )
            master_list.append(self.new_template(params=sub_params, temp_cls=AnalogSubstrate))
            track_spec_list.append(('MX', -1, -1))
            self._ridx_lookup[sub_type].append(row_offset)
            w_list_final.append(top_sub_w)

        mos_kwargs = [{}] + mos_kwargs + [{}]
        return track_spec_list, master_list, mos_kwargs, w_list_final

    def _place_helper(self, bot_ext_w, track_spec_list, master_list, gds_space, hm_layer, mos_pitch, tot_pitch, dy):

        # based on line-end spacing, find the number of horizontal tracks
        # needed between routing tracks of adjacent blocks.
        hm_sep = self.grid.get_line_end_space_tracks(hm_layer - 1, hm_layer, 1)
        via_ext = self.grid.get_via_extensions(hm_layer - 1, 1, 1, unit_mode=True)[0]
        hm_w = self.grid.get_track_width(hm_layer, 1, unit_mode=True)
        conn_delta = via_ext + hm_w // 2
        fg = self._tech_cls.get_analog_unit_fg()

        # place bottom substrate at dy
        y_cur = dy
        tr_next = 0
        y_list = []
        ext_info_list = []
        gtr_intv = []
        dtr_intv = []
        num_master = len(master_list)
        lch_unit = int(round(self._lch / self.grid.layout_unit / self.grid.resolution))
        for idx in range(num_master):
            # step 1: place current master
            y_list.append(y_cur)
            cur_master = master_list[idx]
            y_top_cur = y_cur + cur_master.prim_bound_box.height_unit
            # step 2: find how many tracks current block uses
            cur_orient, cur_ng, cur_nds = track_spec_list[idx]
            if cur_ng < 0:
                # substrate.  A substrate block only use tracks within its array bounding box.
                if cur_orient == 'R0':
                    yarr_bot = y_cur + cur_master.array_box.bottom_unit
                    yarr_top = y_cur + cur_master.array_box.top_unit
                else:
                    yarr_bot = y_cur
                    yarr_top = y_cur + cur_master.array_box.height_unit
                tr_next = self.grid.find_next_track(hm_layer, yarr_bot, half_track=True, mode=1, unit_mode=True)
                tr_tmp = self.grid.find_next_track(hm_layer, yarr_top, half_track=True, mode=1, unit_mode=True)
                dtr_intv.append((tr_next, tr_tmp))
                gtr_intv.append((tr_tmp, tr_tmp))
            else:
                # transistor.  find first unused track.
                if cur_orient == 'R0':
                    # drain/source tracks on top.  find bottom drain/source track (take gds_space into account).
                    g_conn_yb, g_conn_yt = cur_master.get_g_conn_y()
                    d_conn_yb, d_conn_yt = cur_master.get_d_conn_y()
                    g_conn_yt += y_cur
                    d_conn_yb += y_cur
                    d_conn_yt += y_cur
                    tr_g_top = self.grid.coord_to_nearest_track(hm_layer, g_conn_yt - conn_delta, half_track=True,
                                                                mode=-1, unit_mode=True)
                    tr_ds_bot = self.grid.coord_to_nearest_track(hm_layer, d_conn_yb + conn_delta, half_track=True,
                                                                 mode=1, unit_mode=True)
                    tr_ds_bot = max(tr_ds_bot, tr_g_top + gds_space + 1)
                    tr_ds_top1 = tr_ds_bot + cur_nds - 1
                    tr_ds_top2 = self.grid.coord_to_nearest_track(hm_layer, d_conn_yt - conn_delta, half_track=True,
                                                                  mode=1, unit_mode=True)
                    tr_ds_top = max(tr_ds_top1, tr_ds_top2)
                    tr_tmp = tr_ds_top + 1 + hm_sep
                    gtr_intv.append((tr_g_top + 1 - cur_ng, tr_g_top + 1))
                    dtr_intv.append((tr_ds_bot, tr_ds_top + 1))
                else:
                    # gate tracks on top
                    g_conn_yb, g_conn_yt = cur_master.get_g_conn_y()
                    d_conn_yb, d_conn_yt = cur_master.get_d_conn_y()
                    g_conn_yt = y_top_cur - g_conn_yt
                    g_conn_yb = y_top_cur - g_conn_yb
                    d_conn_yb = y_top_cur - d_conn_yb
                    tr_ds_top = self.grid.coord_to_nearest_track(hm_layer, d_conn_yb - conn_delta, half_track=True,
                                                                 mode=-1, unit_mode=True)
                    tr_g_bot = self.grid.coord_to_nearest_track(hm_layer, g_conn_yt + conn_delta, half_track=True,
                                                                mode=1, unit_mode=True)
                    tr_ds_top = min(tr_ds_top, tr_g_bot - 1 - gds_space)
                    tr_g_top1 = tr_g_bot + cur_ng - 1
                    tr_g_top2 = self.grid.coord_to_nearest_track(hm_layer, g_conn_yb - conn_delta, half_track=True,
                                                                 mode=1, unit_mode=True)
                    tr_g_top = max(tr_g_top1, tr_g_top2)
                    tr_tmp = tr_g_top + 1 + hm_sep
                    dtr_intv.append((tr_ds_top + 1 - cur_nds, tr_ds_top + 1))
                    gtr_intv.append((tr_g_bot, tr_g_top + 1))

            tr_next = tr_tmp

            # step 2.5: find minimum Y coordinate of next block based on track information.
            y_tr_last_top = self.grid.get_wire_bounds(hm_layer, tr_next - 1, unit_mode=True)[1]
            y_next_min = -(-y_tr_last_top // mos_pitch) * mos_pitch

            # step 3: compute extension to next master and location of next master
            if idx + 1 < num_master:
                # step 3A: figure out minimum extension width
                next_master = master_list[idx + 1]
                next_orient, next_ng, next_nds = track_spec_list[idx + 1]
                bot_ext_info = cur_master.get_ext_top_info() if cur_orient == 'R0' else cur_master.get_ext_bot_info()
                top_ext_info = next_master.get_ext_bot_info() if next_orient == 'R0' else next_master.get_ext_top_info()
                ext_w_list = self._tech_cls.get_valid_extension_widths(lch_unit, top_ext_info, bot_ext_info)
                min_ext_w = ext_w_list[0]
                if idx == 0:
                    # make sure first extension width is at least bot_ext_w
                    min_ext_w = max(min_ext_w, bot_ext_w)
                # increase extension width if we need to place next block higher
                test_ext_w = (y_next_min - y_top_cur) // mos_pitch  # type: int
                min_ext_w = max(min_ext_w, test_ext_w)
                # make sure min_ext_w is a valid width
                if min_ext_w not in ext_w_list and min_ext_w < ext_w_list[-1]:
                    for tmp_ext_w in ext_w_list:
                        if min_ext_w < tmp_ext_w:
                            min_ext_w = tmp_ext_w
                            break
                # update y_next_min
                y_next_min = max(y_next_min, y_top_cur + min_ext_w * mos_pitch)
                # step 3B: figure out placement of next block
                if idx + 1 == num_master - 1:
                    # this is the last block.  Place it such that the overall height is multiples of tot_pitch.
                    next_height = next_master.prim_bound_box.height_unit
                    y_top_min = y_next_min + next_height
                    y_top = -(-y_top_min // tot_pitch) * tot_pitch
                    y_next = y_top - next_height
                    # make sure we both have valid extension width and last block is on tot_pitch.
                    # Iterate until we get it
                    ext_w = (y_next - y_top_cur) // mos_pitch
                    while ext_w not in ext_w_list and ext_w < ext_w_list[-1]:
                        # find next extension block
                        for tmp_ext_w in ext_w_list:
                            if ext_w < tmp_ext_w:
                                ext_w = tmp_ext_w
                                break
                        # update y_next
                        y_next = y_top_cur + ext_w * mos_pitch
                        # place last block such that it is on tot_pitch
                        y_top_min = y_next + next_height
                        y_top = -(-y_top_min // tot_pitch) * tot_pitch
                        y_next = y_top - next_height
                        # recalculate ext_w
                        ext_w = (y_next - y_top_cur) // mos_pitch
                else:
                    if next_ng < 0:
                        # substrate block.  place as close to current block as possible
                        y_next = y_next_min
                    else:
                        if next_orient == 'R0':
                            # Find minimum Y coordinate to have enough gate tracks.
                            y_gtr_last_mid = self.grid.track_to_coord(hm_layer, tr_next + next_ng - 1, unit_mode=True)
                            g_conn_yt = next_master.get_g_conn_y()[1]
                            y_next = -(-(y_gtr_last_mid - g_conn_yt + conn_delta) // mos_pitch) * mos_pitch
                            y_next = max(y_next, y_next_min)
                        else:
                            # find minimum Y coordinate to have enough drain/source tracks.
                            dtr_last_idx = tr_next + next_nds + gds_space - 1
                            y_dtr_last_mid = self.grid.track_to_coord(hm_layer, dtr_last_idx, unit_mode=True)
                            d_conn_yb = next_master.get_d_conn_y()[0]
                            y_coord = next_master.array_box.height_unit - d_conn_yb
                            y_next = -(-(y_dtr_last_mid - y_coord + conn_delta) // mos_pitch) * mos_pitch
                            y_next = max(y_next, y_next_min)
                    ext_w = (y_next - y_top_cur) // mos_pitch
                    # make sure ext_w is a valid width
                    if ext_w not in ext_w_list and ext_w < ext_w_list[-1]:
                        for tmp_ext_w in ext_w_list:
                            if ext_w < tmp_ext_w:
                                ext_w = tmp_ext_w
                                break
                if 'mos_type' in cur_master.params:
                    bot_mtype = cur_master.params['mos_type']
                else:
                    bot_mtype = cur_master.params['sub_type']
                if 'mos_type' in next_master.params:
                    top_mtype = next_master.params['mos_type']
                else:
                    top_mtype = next_master.params['sub_type']
                ext_params = dict(
                    lch=cur_master.params['lch'],
                    w=ext_w,
                    bot_mtype=bot_mtype,
                    top_mtype=top_mtype,
                    bot_thres=cur_master.params['threshold'],
                    top_thres=next_master.params['threshold'],
                    fg=fg,
                    top_ext_info=top_ext_info,
                    bot_ext_info=bot_ext_info,
                )
                ext_info_list.append((ext_w, ext_params))
                # step 3D: update y_cur
                y_cur = y_next

        # return placement result.
        return y_list, ext_info_list, tr_next, gtr_intv, dtr_intv

    def _place(self, fg_tot, track_spec_list, master_list, gds_space, guard_ring_nf, top_layer,
               left_end, right_end, bot_end, top_end):
        """
        Placement strategy: make overall block match mos_pitch and horizontal track pitch, try to
        center everything between the top and bottom substrates.
        """
        # find total pitch of the analog base.
        dum_layer = self.dum_conn_layer
        mconn_layer = self.mos_conn_layer
        hm_layer = mconn_layer + 1
        mos_pitch = self._tech_cls.get_mos_pitch(unit_mode=True)
        tot_pitch = self._layout_info.vertical_pitch_unit

        # make end rows
        bot_end_params = dict(
            lch=self._lch,
            sub_type=master_list[0].params['sub_type'],
            threshold=master_list[0].params['threshold'],
            is_end=bot_end,
            top_layer=top_layer,
        )
        bot_end_master = self.new_template(params=bot_end_params, temp_cls=AnalogEndRow)
        top_end_params = dict(
            lch=self._lch,
            sub_type=master_list[-1].params['sub_type'],
            threshold=master_list[-1].params['threshold'],
            is_end=top_end,
            top_layer=top_layer,
        )
        top_end_master = self.new_template(params=top_end_params, temp_cls=AnalogEndRow)
        # compute Y coordinate shift from adding end row
        dy = bot_end_master.array_box.height_unit

        # first try: place everything, but blocks as close to the bottom as possible.
        y_list, ext_list, tot_ntr, gtr_intv, dtr_intv = self._place_helper(0, track_spec_list, master_list, gds_space,
                                                                           hm_layer, mos_pitch, tot_pitch, dy)
        ext_first, ext_last = ext_list[0][0], ext_list[-1][0]
        print('ext_w0 = %d, ext_wend=%d, tot_ntr=%d' % (ext_first, ext_last, tot_ntr))
        while ext_first < ext_last - 1:
            # if the bottom extension width is smaller than the top extension width (and differ by more than 1),
            # then we can potentially get a more centered placement by increasing the minimum bottom extenison width.
            bot_ext_w = ext_first + 1
            y_next, ext_next, tot_ntr_next, gnext, dnext = self._place_helper(bot_ext_w, track_spec_list, master_list,
                                                                              gds_space, hm_layer, mos_pitch,
                                                                              tot_pitch, dy)
            ext_first_next, ext_last_next = ext_next[0][0], ext_next[-1][0]
            print('ext_w0 = %d, ext_wend=%d, tot_ntr=%d' % (ext_first_next, ext_last_next, tot_ntr_next))
            if tot_ntr_next > tot_ntr or abs(ext_last - ext_first) < abs(ext_last_next - ext_first_next):
                # if either we increase the overall size of analog base, or we get a more
                # unbalanced placement, then it's not worth it anymore.
                print('abort')
                break
            else:
                # update the optimal placement strategy.
                y_list, ext_list, tot_ntr = y_next, ext_next, tot_ntr_next
                ext_last, ext_first = ext_last_next, ext_first_next
                gtr_intv, dtr_intv = gnext, dnext
                print('pick')

        # at this point we've found the optimal placement.  Place instances
        import pdb
        pdb.set_trace()
        fg_unit = self._tech_cls.get_analog_unit_fg()
        nx = fg_tot // fg_unit
        spx = fg_unit * self.sd_pitch_unit
        self.array_box = BBox.get_invalid_bbox()
        top_bound_box = BBox.get_invalid_bbox()
        self._gtr_intv = gtr_intv
        self._dstr_intv = dtr_intv
        ext_list.append((0, None))
        gr_vss_warrs = []
        gr_vdd_warrs = []
        gr_vss_dum_warrs = []
        gr_vdd_dum_warrs = []
        # add end rows to list
        y_list.insert(0, 0)
        y_list.append(y_list[-1] + master_list[-1].array_box.height_unit)
        ext_list.insert(0, (0, None))
        ext_list.append((0, None))
        master_list.insert(0, bot_end_master)
        master_list.append(top_end_master)
        track_spec_list.insert(0, ('R0', 0, 0))
        track_spec_list.append(('MX', 0, 0))
        # draw
        for ybot, ext_info, master, track_spec in zip(y_list, ext_list, master_list, track_spec_list):
            orient = track_spec[0]
            edge_layout_info = master.get_edge_layout_info()
            edgel_params = dict(
                top_layer=top_layer,
                is_end=left_end,
                guard_ring_nf=guard_ring_nf,
                name_id=master.get_layout_basename(),
                layout_info=edge_layout_info,
            )
            edgel_master = self.new_template(params=edgel_params, temp_cls=AnalogEdge)
            edgel = self.add_instance(edgel_master, orient=orient)
            cur_box = edgel.translate_master_box(edgel_master.prim_bound_box)
            yo = ybot - cur_box.bottom_unit
            edgel.move_by(dy=yo, unit_mode=True)
            inst_xo = cur_box.right_unit
            inst_loc = (inst_xo, yo)
            inst = self.add_instance(master, loc=inst_loc, orient=orient, nx=nx, spx=spx, unit_mode=True)
            if isinstance(master, AnalogSubstrate):
                conn_layout_info = edge_layout_info.copy()
                conn_layout_info['fg'] = fg_tot
                conn_params = dict(
                    layout_info=conn_layout_info,
                    layout_name=master.get_layout_basename() + '_subconn',
                )
                conn_master = self.new_template(params=conn_params, temp_cls=AnalogSubstrateConn)
                conn_inst = self.add_instance(conn_master, loc=inst_loc, orient=orient, unit_mode=True)
                sub_type = master.params['sub_type']
                # save substrate instance
                if sub_type == 'ptap':
                    self._ptap_list.append(conn_inst)
                    self._ptap_exports.append(set())
                elif sub_type == 'ntap':
                    self._ntap_list.append(conn_inst)
                    self._ntap_exports.append(set())

            if not isinstance(master, AnalogEndRow):
                sd_yc = inst.translate_master_location((0, master.get_sd_yc()), unit_mode=True)[1]
                self._sd_yc_list.append(sd_yc)

            if orient == 'R0':
                orient_r = 'MY'
            else:
                orient_r = 'R180'
            edger_xo = inst.array_box.right_unit + edgel_master.prim_bound_box.width_unit
            edger_loc = edger_xo, yo
            edger_params = dict(
                top_layer=top_layer,
                is_end=right_end,
                guard_ring_nf=guard_ring_nf,
                name_id=master.get_layout_basename(),
                layout_info=edge_layout_info,
            )
            edger_master = self.new_template(params=edger_params, temp_cls=AnalogEdge)
            edger = self.add_instance(edger_master, loc=edger_loc, orient=orient_r, unit_mode=True)
            self.array_box = self.array_box.merge(edgel.array_box).merge(edger.array_box)
            top_bound_box = top_bound_box.merge(edgel.bound_box).merge(edger.bound_box)
            edge_inst_list = [edgel, edger]
            if ext_info[1] is not None and (ext_info[0] > 0 or self._tech_cls.draw_zero_extension()):
                ext_master = self.new_template(params=ext_info[1], temp_cls=AnalogMOSExt)
                ext_edge_layout_info = ext_master.get_edge_layout_info()
                ext_edgel_params = dict(
                    top_layer=top_layer,
                    is_end=left_end,
                    guard_ring_nf=guard_ring_nf,
                    name_id=ext_master.get_layout_basename(),
                    layout_info=ext_edge_layout_info,
                )
                ext_edgel_master = self.new_template(params=ext_edgel_params, temp_cls=AnalogEdge)
                yo = inst.array_box.top_unit
                edgel = self.add_instance(ext_edgel_master, loc=(0, yo), unit_mode=True)
                self.add_instance(ext_master, loc=(inst_xo, yo), nx=nx, spx=spx, unit_mode=True)
                ext_edger_params = dict(
                    top_layer=top_layer,
                    is_end=right_end,
                    guard_ring_nf=guard_ring_nf,
                    name_id=ext_master.get_layout_basename(),
                    layout_info=ext_edge_layout_info,
                )
                ext_edger_master = self.new_template(params=ext_edger_params, temp_cls=AnalogEdge)
                edger = self.add_instance(ext_edger_master, loc=(edger_xo, yo), orient='MY', unit_mode=True)
                edge_inst_list.append(edgel)
                edge_inst_list.append(edger)

            # gather guard ring ports
            for inst in edge_inst_list:
                if inst.has_port('VDD'):
                    gr_vdd_warrs.extend(inst.get_all_port_pins('VDD', layer=mconn_layer))
                    gr_vdd_dum_warrs.extend(inst.get_all_port_pins('VDD', layer=dum_layer))
                elif inst.has_port('VSS'):
                    gr_vss_warrs.extend(inst.get_all_port_pins('VSS', layer=mconn_layer))
                    gr_vss_dum_warrs.extend(inst.get_all_port_pins('VSS', layer=dum_layer))

        # connect body guard rings together
        self._gr_vdd_warrs = self.connect_wires(gr_vdd_warrs)
        self._gr_vss_warrs = self.connect_wires(gr_vss_warrs)
        self.connect_wires(gr_vdd_dum_warrs)
        self.connect_wires(gr_vss_dum_warrs)

        # set array box/size/draw PR boundary
        self.set_size_from_bound_box(top_layer, top_bound_box)
        self.add_cell_boundary(self.bound_box)

    def draw_base(self,  # type: AnalogBase
                  lch,  # type: float
                  fg_tot,  # type: int
                  ptap_w,  # type: Union[float, int]
                  ntap_w,  # type: Union[float, int]
                  nw_list,  # type: List[Union[float, int]]
                  nth_list,  # type: List[str]
                  pw_list,  # type: List[Union[float, int]]
                  pth_list,  # type: List[str]
                  gds_space=0,  # type: int
                  ng_tracks=None,  # type: Optional[List[int]]
                  nds_tracks=None,  # type: Optional[List[int]]
                  pg_tracks=None,  # type: Optional[List[int]]
                  pds_tracks=None,  # type: Optional[List[int]]
                  n_orientations=None,  # type: Optional[List[str]]
                  p_orientations=None,  # type: Optional[List[str]]
                  guard_ring_nf=0,  # type: int
                  n_kwargs=None,  # type: Optional[Dict[str, Any]]
                  p_kwargs=None,  # type: Optional[Dict[str, Any]]
                  pgr_w=None,  # type: Optional[Union[float, int]]
                  ngr_w=None,  # type: Optional[Union[float, int]]
                  min_fg_sep=0,  # type: int
                  end_mode=15,  # type: int
                  top_layer=None,  # type: Optional[int]
                  **kwargs
                  ):
        # type: (...) -> None
        """Draw the analog base.

        This method must be called first.

        Parameters
        ----------
        lch : float
            the transistor channel length, in meters
        fg_tot : int
            total number of fingers for each row.
        ptap_w : Union[float, int]
            pwell substrate contact width.
        ntap_w : Union[float, int]
            nwell substrate contact width.
        gds_space : int
            number of tracks to reserve as space between gate and drain/source tracks.
        nw_list : List[Union[float, int]]
            a list of nmos width for each row, from bottom to top.
        nth_list: List[str]
            a list of nmos threshold flavor for each row, from bottom to top.
        pw_list : List[Union[float, int]]
            a list of pmos width for each row, from bottom to top.
        pth_list : List[str]
            a list of pmos threshold flavor for each row, from bottom to top.
        ng_tracks : Optional[List[int]]
            number of nmos gate tracks per row, from bottom to top.  Defaults to 1.
        nds_tracks : Optional[List[int]]
            number of nmos drain/source tracks per row, from bottom to top.  Defaults to 1.
        pg_tracks : Optional[List[int]]
            number of pmos gate tracks per row, from bottom to top.  Defaults to 1.
        pds_tracks : Optional[List[int]]
            number of pmos drain/source tracks per row, from bottom to top.  Defaults to 1.
        n_orientations : Optional[List[str]]
            orientation of each nmos row. Defaults to all 'R0'.
        p_orientations : Optional[List[str]]
            orientation of each pmos row.  Defaults to all 'MX'.
        guard_ring_nf : int
            width of guard ring in number of fingers.  0 to disable guard ring.
        n_kwargs : Optional[Dict[str, Any]]
            Optional keyword arguments for each nmos row.
        p_kwargs : Optional[Dict[str, Any]]
            Optional keyword arguments for each pmos row.
        pgr_w : Optional[Union[float, int]]
            pwell guard ring substrate contact width.
        ngr_w : Optional[Union[float, int]]
            nwell guard ring substrate contact width.
        min_fg_sep : int
            minimum number of fingers between different transistors.
        end_mode : int
            right/left/top/bottom end mode flag.  This is a 4-bit integer.  If bit 0 (LSB) is 1, then
            we assume there are no blocks abutting the bottom.  If bit 1 is 1, we assume there are no
            blocks abutting the top.  bit 2 and bit 3 (MSB) corresponds to left and right, respectively.
            The default value is 15, which means we assume this AnalogBase is surrounded by empty spaces.
        top_layer : Optional[int]
            The top metal layer this block will use.  Defaults to the horizontal layer above mos connection layer.
            The top metal layer decides the quantization of the overall bounding box and the array box.  As
            the result, the margin between edge of the overall bounding box and the edge of array box is
            determined by the block pitch.
        **kwargs:
            Other optional arguments.
        """
        numn = len(nw_list)
        nump = len(pw_list)
        # error checking
        if numn == 0 and nump == 0:
            raise ValueError('Cannot make empty AnalogBase.')

        # make AnalogBaseInfo object.  Also update routing grid.
        self._layout_info = AnalogBaseInfo(self.grid, lch, guard_ring_nf,
                                           top_layer=top_layer, end_mode=end_mode, min_fg_sep=min_fg_sep)
        self.grid = self._layout_info.grid

        # initialize private attributes.
        self._lch = lch
        self._w_list = []
        self._fg_tot = fg_tot
        self._sd_yc_list = []
        self._mos_kwargs_list = []

        self._n_intvs = [IntervalSet() for _ in range(numn)]
        self._p_intvs = [IntervalSet() for _ in range(nump)]
        self._capn_intvs = [IntervalSet() for _ in range(numn)]
        self._capp_intvs = [IntervalSet() for _ in range(nump)]

        self._ridx_lookup = dict(nch=[], pch=[], ntap=[], ptap=[])

        self._ntap_list = []
        self._ptap_list = []
        self._ptap_exports = []
        self._ntap_exports = []

        if pgr_w is None:
            pgr_w = ntap_w
        if ngr_w is None:
            ngr_w = ptap_w

        if guard_ring_nf == 0:
            pgr_w = ngr_w = 0

        # place transistor blocks
        master_list = []
        track_spec_list = []
        bot_sub_end = end_mode % 2
        top_sub_end = (end_mode & 2) >> 1
        left_end = (end_mode & 4) >> 2
        right_end = (end_mode & 8) >> 3
        top_nsub_end = top_sub_end if not pw_list else 0
        bot_psub_end = bot_sub_end if not nw_list else 0
        top_layer = self._layout_info.top_layer
        # make NMOS substrate/transistor masters.
        tr_list, m_list, n_kwargs, nw_list = self._make_masters('nch', self._lch, ptap_w, bot_sub_end, ngr_w,
                                                                top_nsub_end, nw_list, nth_list, ng_tracks,
                                                                nds_tracks, n_orientations, n_kwargs, 0)
        master_list.extend(m_list)
        track_spec_list.extend(tr_list)
        self._mos_kwargs_list.extend(n_kwargs)
        self._w_list.extend(nw_list)
        # make PMOS substrate/transistor masters.
        tr_list, m_list, p_kwargs, pw_list = self._make_masters('pch', self._lch, pgr_w, bot_psub_end, ntap_w,
                                                                top_sub_end, pw_list, pth_list, pg_tracks,
                                                                pds_tracks, p_orientations, p_kwargs, len(m_list))
        master_list.extend(m_list)
        track_spec_list.extend(tr_list)
        self._mos_kwargs_list.extend(p_kwargs)
        self._w_list.extend(pw_list)
        self._orient_list = [item[0] for item in track_spec_list]

        # place masters according to track specifications.  Try to center transistors
        self._place(fg_tot, track_spec_list, master_list, gds_space, guard_ring_nf, top_layer,
                    left_end != 0, right_end != 0, bot_sub_end != 0, top_sub_end != 0)

    def _connect_substrate(self,  # type: AnalogBase
                           sub_type,  # type: str
                           sub_list,  # type: List[Instance]
                           row_idx_list,  # type: List[int]
                           lower=None,  # type: Optional[Union[float, int]]
                           upper=None,  # type: Optional[Union[float, int]]
                           sup_wires=None,  # type: Optional[Union[WireArray, List[WireArray]]]
                           sup_margin=0,  # type: int
                           unit_mode=False  # type: bool
                           ):
        """Connect all given substrates to horizontal tracks

        Parameters
        ----------
        sub_type : str
            substrate type.  Either 'ptap' or 'ntap'.
        sub_list : List[Instance]
            list of substrates to connect.
        row_idx_list : List[int]
            list of substrate row indices.
        lower : Optional[Union[float, int]]
            lower supply track coordinates.
        upper : Optional[Union[float, int]]
            upper supply track coordinates.
        sup_wires : Optional[Union[WireArray, List[WireArray]]]
            If given, will connect these horizontal wires to supply on mconn layer.
        sup_margin : int
            supply wires mconn layer connection horizontal margin in number of tracks.
        unit_mode : bool
            True if lower/upper is specified in resolution units.

        Returns
        -------
        track_buses : list[bag.layout.routing.WireArray]
            list of substrate tracks buses.
        """
        port_name = 'VDD' if sub_type == 'ntap' else 'VSS'

        if sup_wires is not None and isinstance(sup_wires, WireArray):
            sup_wires = [sup_wires]
        else:
            pass

        sub_warr_list = []
        hm_layer = self.mos_conn_layer + 1
        for row_idx, subinst in zip(row_idx_list, sub_list):
            # Create substrate TrackID
            sub_row_idx = self._find_row_index(sub_type, row_idx)
            dtr_intv = self._dstr_intv[sub_row_idx]
            ntr = dtr_intv[1] - dtr_intv[0]
            sub_w = self.grid.get_max_track_width(hm_layer, 1, ntr, half_end_space=False)
            track_id = TrackID(hm_layer, dtr_intv[0] + (ntr - 1) / 2, width=sub_w)

            # get all wires to connect to supply.
            warr_iter_list = [subinst.get_port(port_name).get_pins(self.mos_conn_layer)]
            if port_name == 'VDD':
                warr_iter_list.append(self._gr_vdd_warrs)
            else:
                warr_iter_list.append(self._gr_vss_warrs)

            warr_list = list(chain(*warr_iter_list))
            track_warr = self.connect_to_tracks(warr_list, track_id, track_lower=lower, track_upper=upper,
                                                unit_mode=unit_mode)
            sub_warr_list.append(track_warr)
            if sup_wires is not None:
                wlower, wupper = warr_list[0].lower, warr_list[0].upper
                for conn_warr in sup_wires:
                    if conn_warr.layer_id != hm_layer:
                        raise ValueError('vdd/vss wires must be on layer %d' % hm_layer)
                    tmin, tmax = self.grid.get_overlap_tracks(hm_layer - 1, conn_warr.lower,
                                                              conn_warr.upper, half_track=True)
                    new_warr_list = []
                    for warr in warr_list:
                        for tid in warr.track_id:
                            if tid > tmax:
                                break
                            elif tmin <= tid:
                                if not self.mos_conn_track_used(tid, margin=sup_margin):
                                    new_warr_list.append(
                                        WireArray(TrackID(hm_layer - 1, tid), lower=wlower, upper=wupper))
                    self.connect_to_tracks(new_warr_list, conn_warr.track_id)

        return sub_warr_list

    def fill_dummy(self,  # type: AnalogBase
                   lower=None,  # type: Optional[Union[float, int]]
                   upper=None,  # type: Optional[Union[float, int]]
                   vdd_warrs=None,  # type: Optional[Union[WireArray, List[WireArray]]]
                   vss_warrs=None,  # type: Optional[Union[WireArray, List[WireArray]]]
                   sup_margin=0,  # type: int
                   unit_mode=False  # type: bool
                   ):
        # type: (...) -> Tuple[List[WireArray], List[WireArray]]
        """Draw dummy/separator on all unused transistors.

        This method should be called last.

        Parameters
        ----------
        lower : Optional[Union[float, int]]
            lower coordinate for the supply tracks.
        upper : Optional[Union[float, int]]
            upper coordinate for the supply tracks.
        vdd_warrs : Optional[Union[WireArray, List[WireArray]]]
            vdd wires to be connected.
        vss_warrs : Optional[Union[WireArray, List[WireArray]]]
            vss wires to be connected.
        sup_margin : int
            vdd/vss wires mos conn layer margin in number of tracks.
        unit_mode : bool
            True if lower/upper are specified in resolution units.

        Returns
        -------
        ptap_wire_arrs : List[WireArray]
            list of P-tap substrate WireArrays.
        ntap_wire_arrs : List[WireArray]
            list of N-tap substrate WireArrays.
        """
        # invert PMOS/NMOS IntervalSet to get unconnected dummies
        total_intv = (0, self._fg_tot)
        p_intvs = [intv_set.get_complement(total_intv) for intv_set in self._p_intvs]
        n_intvs = [intv_set.get_complement(total_intv) for intv_set in self._n_intvs]

        # connect NMOS dummies
        top_tracks = None
        top_sub_inst = None
        if self._ptap_list:
            bot_sub_inst = self._ptap_list[0]
            bot_tracks = self._ptap_exports[0]
            if len(self._ptap_list) > 1:
                top_sub_inst = self._ptap_list[1]
                top_tracks = self._ptap_exports[1]
            self._fill_dummy_helper('nch', n_intvs, self._capn_intvs, self._capn_wires, bot_sub_inst, top_sub_inst,
                                    bot_tracks, top_tracks, not self._ntap_list)

        # connect PMOS dummies
        bot_tracks = None
        bot_sub_inst = None
        if self._ntap_list:
            top_sub_inst = self._ntap_list[-1]
            top_tracks = self._ntap_exports[-1]
            if len(self._ntap_list) > 1:
                bot_sub_inst = self._ntap_list[0]
                bot_tracks = self._ntap_exports[0]
            self._fill_dummy_helper('pch', p_intvs, self._capp_intvs, self._capp_wires, bot_sub_inst, top_sub_inst,
                                    bot_tracks, top_tracks, not self._ptap_list)

        # connect NMOS substrates to horizontal tracks.
        if not self._ntap_list:
            # connect both substrates if NMOS only
            ptap_wire_arrs = self._connect_substrate('ptap', self._ptap_list, list(range(len(self._ptap_list))),
                                                     lower=lower, upper=upper, sup_wires=vss_warrs,
                                                     sup_margin=sup_margin, unit_mode=unit_mode)
        elif self._ptap_list:
            # NMOS exists, only connect bottom substrate to upper level metal
            ptap_wire_arrs = self._connect_substrate('ptap', self._ptap_list[:1], [0],
                                                     lower=lower, upper=upper, sup_wires=vss_warrs,
                                                     sup_margin=sup_margin, unit_mode=unit_mode)
        else:
            ptap_wire_arrs = []

        # connect PMOS substrates to horizontal tracks.
        if not self._ptap_list:
            # connect both substrates if PMOS only
            ntap_wire_arrs = self._connect_substrate('ntap', self._ntap_list, list(range(len(self._ntap_list))),
                                                     lower=lower, upper=upper, sup_wires=vdd_warrs,
                                                     sup_margin=sup_margin, unit_mode=unit_mode)
        elif self._ntap_list:
            # PMOS exists, only connect top substrate to upper level metal
            ntap_wire_arrs = self._connect_substrate('ntap', self._ntap_list[-1:], [len(self._ntap_list) - 1],
                                                     lower=lower, upper=upper, sup_wires=vdd_warrs,
                                                     sup_margin=sup_margin, unit_mode=unit_mode)
        else:
            ntap_wire_arrs = []

        return ptap_wire_arrs, ntap_wire_arrs

    def _fill_dummy_helper(self,  # type: AnalogBase
                           mos_type,  # type: str
                           intv_set_list,  # type: List[IntervalSet]
                           cap_intv_set_list,  # type: List[IntervalSet]
                           cap_wires_dict,  # type: Dict[int, List[WireArray]]
                           bot_sub_inst,  # type: Optional[Instance]
                           top_sub_inst,  # type: Optional[Instance]
                           bot_tracks,  # type: List[int]
                           top_tracks,  # type: List[int]
                           export_both  # type: bool
                           ):
        # type: (...) -> None
        """Helper function for figuring out how to connect all dummies to supplies.

        Parameters
        ----------
        mos_type: str
            the transistor type.  Either 'pch' or 'nch'.
        intv_set_list : List[IntervalSet]
            list of used transistor finger intervals on each transistor row.  Index 0 is bottom row.
        cap_intv_set_list : List[IntervalSet]
            list of used decap transistor finger intervals on each transistor row.  Index 0 is bottom row.
        cap_wires_dict : Dict[int, List[WireArray]]
            dictionary from substrate ID to decap wires that need to connect to that substrate.
            bottom substrate has ID of 1, and top substrate has ID of -1.
        bot_sub_inst : Optional[Instance]
            the bottom substrate instance.
        top_sub_inst : Optional[Instance]
            the top substrate instance.
        bot_tracks : List[int]
            list of port track indices that needs to be exported on bottom substrate.
        top_tracks : List[int]
            list of port track indices that needs to be exported on top substrate.
        export_both : bool
            True if both bottom and top substrate should draw port on mos_conn_layer.
        """
        num_rows = len(intv_set_list)
        bot_conn = top_conn = []

        # step 1: find dummy connection intervals to bottom/top substrates
        num_sub = 0
        if bot_sub_inst is not None:
            num_sub += 1
            bot_conn = self._get_dummy_connections(intv_set_list)
        if top_sub_inst is not None:
            num_sub += 1
            top_conn = self._get_dummy_connections(intv_set_list[::-1])

        # steo 2: make list of dummy transistor intervals and unused dummy track intervals
        unconnected_intv_list = []
        dum_tran_intv_list = []
        # subtract cap interval sets.
        for intv_set, cap_intv_set in zip(intv_set_list, cap_intv_set_list):
            unconnected_intv_list.append(intv_set.copy())
            temp_intv = intv_set.copy()
            for intv in cap_intv_set:
                temp_intv.subtract(intv)
            dum_tran_intv_list.append(temp_intv)

        # step 3: determine if there are tracks that can connect both substrates and all dummies
        if num_sub == 2:
            # we have both top and bottom substrate, so we can connect all dummies together
            all_conn_set = bot_conn[-1]
            del bot_conn[-1]
            del top_conn[-1]

            # remove all intervals connected by all_conn_list.
            for all_conn_intv in all_conn_set:
                for intv_set in unconnected_intv_list:
                    intv_set.remove_all_overlaps(all_conn_intv)
        else:
            all_conn_set = None

        # step 4: select dummy tracks
        bot_dum_only = top_dum_only = False
        if mos_type == 'nch':
            # for NMOS, prioritize connection to bottom substrate.
            port_name = 'VSS'
            bot_dhtr = self._select_dummy_connections(bot_conn, unconnected_intv_list, all_conn_set)
            top_dhtr = self._select_dummy_connections(top_conn, unconnected_intv_list[::-1], all_conn_set)
            top_dum_only = not export_both
        else:
            # for PMOS, prioritize connection to top substrate.
            port_name = 'VDD'
            top_dhtr = self._select_dummy_connections(top_conn, unconnected_intv_list[::-1], all_conn_set)
            bot_dhtr = self._select_dummy_connections(bot_conn, unconnected_intv_list, all_conn_set)
            bot_dum_only = not export_both

        # step 5: create dictionary from dummy half-track index to Y coordinates
        res = self.grid.resolution
        dum_y_table = {}
        if bot_sub_inst is not None:
            sub_yb = bot_sub_inst.get_port(port_name).get_bounding_box(self.grid, self.dum_conn_layer).bottom_unit
            for htr in bot_dhtr[0]:
                dum_y_table[htr] = [sub_yb, sub_yb]
            for warr in cap_wires_dict[1]:
                lower, upper = int(round(warr.lower / res)), int(round(warr.upper / res))
                for tid in warr.track_id:
                    htr = int(2 * tid + 1)
                    if htr in dum_y_table:
                        dum_y = dum_y_table[htr]
                        dum_y[0] = min(dum_y[0], lower)
                        dum_y[1] = max(dum_y[1], upper)
                    else:
                        dum_y_table[htr] = [sub_yb, upper]

        if top_sub_inst is not None:
            sub_yt = top_sub_inst.get_port(port_name).get_bounding_box(self.grid, self.dum_conn_layer).top_unit
            for htr in top_dhtr[0]:
                if htr in dum_y_table:
                    dum_y_table[htr][1] = sub_yt
                else:
                    dum_y_table[htr] = [sub_yt, sub_yt]
            for warr in cap_wires_dict[-1]:
                lower, upper = int(round(warr.lower / res)), int(round(warr.upper / res))
                for tid in warr.track_id:
                    htr = int(2 * tid + 1)
                    if htr in dum_y_table:
                        dum_y = dum_y_table[htr]
                        dum_y[0] = min(dum_y[0], lower)
                        dum_y[1] = max(dum_y[1], upper)
                    else:
                        dum_y_table[htr] = [lower, sub_yt]

        # step 6: draw dummy connections
        for ridx, dum_tran_intv in enumerate(dum_tran_intv_list):
            bot_dist = ridx
            top_dist = num_rows - 1 - ridx
            dum_htr = []
            if bot_dist < len(bot_dhtr):
                dum_htr.extend(bot_dhtr[bot_dist])
            if top_dist < len(top_dhtr):
                dum_htr.extend(top_dhtr[top_dist])
            dum_htr.sort()

            for start, stop in dum_tran_intv:
                used_tracks, yb, yt = self._draw_dummy_sep_conn(mos_type, ridx, start, stop, dum_htr)
                for htr in used_tracks:
                    dum_y = dum_y_table[htr]
                    dum_y[0] = min(dum_y[0], yb)
                    dum_y[1] = max(dum_y[1], yt)

        # step 7: draw dummy tracks to substrates
        dum_layer = self.dum_conn_layer
        for htr, dum_y in dum_y_table.items():
            self.add_wires(dum_layer, (htr - 1) / 2, dum_y[0], dum_y[1], unit_mode=True)

        # update substrate master to only export necessary wires
        if bot_sub_inst is not None:
            bot_dum_tracks = [(htr - 1) / 2 for htr in bot_dhtr[0]]
            self._export_supplies(bot_dum_tracks, bot_tracks, bot_sub_inst, bot_dum_only)
        if top_sub_inst is not None:
            top_dum_tracks = [(htr - 1) / 2 for htr in top_dhtr[0]]
            self._export_supplies(top_dum_tracks, top_tracks, top_sub_inst, top_dum_only)

    def _select_dummy_connections(self,  # type: AnalogBase
                                  conn_list,  # type: List[IntervalSet]
                                  unconnected,  # type: List[IntervalSet]
                                  all_conn_intv_set,  # type: Optional[IntervalSet]
                                  ):
        # type: (...) -> List[List[int]]
        """Helper method for selecting dummy tracks to connect dummies.

        First, look at the tracks that connect the most rows of dummy.  Try to use
        as many of these tracks as possible while making sure they at least connect one
        unconnected dummy.  When done, repeat on dummy tracks that connect fewer rows.

        Parameters
        ----------
        conn_list : List[IntervalSet]
            list of dummy finger intervals.  conn_list[x] contains dummy finger intervals that
            connects exactly x+1 rows.
        unconnected : List[IntervalSet]
            list of unconnected dummy finger intervals on each row.
        all_conn_intv_set : Optional[IntervalSet]
            dummy finger intervals that connect all rows.

        Returns
        -------
        dum_tracks_list : List[List[int]]
            dum_tracks_list[x] contains dummy half-track indices to draw on row X.
        """
        # step 1: find dummy tracks that connect all rows and both substrates
        if all_conn_intv_set is not None:
            dum_tracks = []
            for intv in all_conn_intv_set:
                dum_tracks.extend(self._fg_intv_to_dum_tracks(intv))
            dum_tracks_list = [dum_tracks]
        else:
            dum_tracks_list = [[]]

        # step 2: find dummy tracks that connects fewer rows
        for idx in range(len(conn_list) - 1, -1, -1):
            conn_intvs = conn_list[idx]
            cur_select_list = []
            # select finger intervals
            for intv in conn_intvs:
                select = False
                for j in range(idx + 1):
                    dummy_intv_set = unconnected[j]
                    if dummy_intv_set.has_overlap(intv):
                        select = True
                        break
                if select:
                    cur_select_list.append(intv)
            # remove connected dummy intervals, and convert finger intervals to tracks
            dum_tracks = []
            for intv in cur_select_list:
                for j in range(idx + 1):
                    unconnected[j].remove_all_overlaps(intv)
                dum_tracks.extend(self._fg_intv_to_dum_tracks(intv))

            # merge with previously selected tracks
            dum_tracks.extend(dum_tracks_list[-1])
            dum_tracks.sort()
            dum_tracks_list.append(dum_tracks)

        # flip dum_tracks_list order
        dum_tracks_list.reverse()
        return dum_tracks_list

    def _fg_intv_to_dum_tracks(self, intv):
        # type: (Tuple[int, int]) -> List[int]
        """Given a dummy finger interval, convert to dummy half-tracks.

        Parameters
        ----------
        intv : Tuple[int, int]
            the dummy finger interval.

        Returns
        -------
        dum_tracks : List[int]
            list of dummy half-track indices.
        """
        layout_info = self._layout_info
        dum_layer = self.dum_conn_layer

        col0, col1 = intv
        xl = layout_info.col_to_coord(col0, unit_mode=True)
        xr = layout_info.col_to_coord(col1, unit_mode=True)
        htr0 = int(1 + 2 * self.grid.coord_to_track(dum_layer, xl, unit_mode=True))
        htr1 = int(1 + 2 * self.grid.coord_to_track(dum_layer, xr, unit_mode=True))

        htr_pitch = self._dum_conn_pitch * 2
        start, stop = htr0 + 2, htr1
        left_adj, right_adj = True, True
        if col0 == 0:
            start = htr0
            left_adj = False
        if col1 == self._fg_tot:
            stop = htr1 + 2
            right_adj = False

        # see if we can leave some space between signal and dummy track
        if left_adj and stop - start > 2:
            start += 2
            if not right_adj:
                num_pitch = (stop - 2 - start) // htr_pitch
                start = max(start, stop - 2 - num_pitch * htr_pitch)
        if right_adj and stop - start > 2:
            stop -= 2

        return list(range(start, stop, htr_pitch))

    @classmethod
    def _get_dummy_connections(cls, intv_set_list):
        # type: (List[IntervalSet]) -> List[IntervalSet]
        """Find all dummy tracks that connects one or more rows of dummies.

        Parameters
        ----------
        intv_set_list : List[IntervalSet]
            list of used transistor finger intervals on each transistor row.  Index 0 is bottom row.

        Returns
        -------
        conn_list : List[IntervalSet]
            list of dummy finger intervals.  conn_list[x] contains dummy finger intervals that
            connects exactly x+1 rows of dummies.
        """
        # populate conn_list, such that conn_list[x] contains intervals where you can connect
        # at least x+1 rows of dummies.
        conn_list = []
        for intv_set in intv_set_list:
            if not conn_list:
                conn_list.append(intv_set.copy())
            else:
                conn_list.append(intv_set.get_intersection(conn_list[-1]))

        # subtract adjacent Intervalsets in conn_list
        for idx in range(len(conn_list) - 1):
            cur_intvs, next_intvs = conn_list[idx], conn_list[idx + 1]
            for intv in next_intvs:
                cur_intvs.subtract(intv)

        return conn_list

    def _export_supplies(self, dum_tracks, port_tracks, sub_inst, dum_only):
        x0 = self._layout_info.sd_xc_unit
        dum_tr_offset = self.grid.coord_to_track(self.dum_conn_layer, x0, unit_mode=True) + 0.5
        mconn_tr_offset = self.grid.coord_to_track(self.mos_conn_layer, x0, unit_mode=True) + 0.5
        dum_tracks = [tr - dum_tr_offset for tr in dum_tracks]
        port_tracks = [tr - mconn_tr_offset for tr in port_tracks]
        sub_inst.new_master_with(dum_tracks=dum_tracks, port_tracks=port_tracks,
                                 dummy_only=dum_only)


class SubstrateContact(TemplateBase):
    """A template that draws a single substrate.

    Useful for resistor/capacitor body biasing.

    Parameters
    ----------
    temp_db : TemplateDB
        the template database.
    lib_name : str
        the layout library name.
    params : Dict[str, Any]
        the parameter values.
    used_names : Set[str]
        a set of already used cell names.
    **kwargs
        dictionary of optional parameters.  See documentation of
        :class:`bag.layout.template.TemplateBase` for details.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        super(SubstrateContact, self).__init__(temp_db, lib_name, params, used_names, **kwargs)
        tech_params = self.grid.tech_info.tech_params
        self._tech_cls = tech_params['layout']['mos_tech_class']
        self._layout_info = None
        self._num_fingers = None

    @property
    def port_name(self):
        return 'VDD' if self.params['sub_type'] == 'ntap' else 'VSS'

    @property
    def num_fingers(self):
        return self._num_fingers

    @classmethod
    def default_top_layer(cls, tech_info):
        mos_cls = tech_info.tech_params['layout']['mos_template']
        mconn_layer = mos_cls.port_layer_id()
        return mconn_layer + 1

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        """Returns a dictionary containing default parameter values.

        Override this method to define default parameter values.  As good practice,
        you should avoid defining default values for technology-dependent parameters
        (such as channel length, transistor width, etc.), but only define default
        values for technology-independent parameters (such as number of tracks).

        Returns
        -------
        default_params : Dict[str, Any]
            dictionary of default parameter values.
        """
        return dict(
            well_end_mode=0,
            show_pins=False,
            is_passive=False,
        )

    @classmethod
    def get_params_info(cls):
        # type: () -> Dict[str, str]
        """Returns a dictionary containing parameter descriptions.

        Override this method to return a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : Dict[str, str]
            dictionary from parameter name to description.
        """
        return dict(
            lch='channel length, in meters.',
            w='substrate width, in meters/number of fins.',
            sub_type='substrate type.',
            threshold='substrate threshold flavor.',
            top_layer='the top level layer ID.',
            blk_width='Width of this template in number of top level track pitches.',
            well_width='Width of the well in layout units.  We assume the well is centered horizontally in the block.',
            show_pins='True to show pin labels.',
            well_end_mode='integer flag that controls whether to extend well layer to top/bottom.',
            is_passive='True if this substrate is used as substrate contact for passive devices.',
        )

    def draw_layout(self):
        # type: () -> None
        self._draw_layout_helper(**self.params)

    def _draw_layout_helper(self, lch, w, sub_type, threshold, top_layer, blk_width, well_width, show_pins,
                            well_end_mode, is_passive):
        # type: (float, Union[float, int], str, str, int, int, bool) -> None
        sub_end_mode = 15
        res = self.grid.resolution
        well_width = int(round(well_width / res))

        # get template quantization based on parent grid.
        parent_grid = self.grid
        wtot = parent_grid.get_size_dimension((top_layer, blk_width, 1), unit_mode=True)[0]

        self._layout_info = AnalogBaseInfo(self.grid, lch, 0, None, sub_end_mode)
        sd_pitch = self._layout_info.sd_pitch_unit
        self.grid = self._layout_info.grid

        hm_layer = self._layout_info.mconn_port_layer + 1

        if top_layer < hm_layer:
            raise ValueError('SubstrateContact top layer must be >= %d' % hm_layer)

        # compute template width in number of sd pitches
        q = well_width // sd_pitch
        # find maximum number of fingers we can draw
        bin_iter = BinaryIterator(1, None)
        while bin_iter.has_next():
            cur_fg = bin_iter.get_next()
            num_sd = self._layout_info.get_total_width(cur_fg)
            if num_sd == q:
                bin_iter.save()
                break
            elif num_sd < q:
                bin_iter.save()
                bin_iter.up()
            else:
                bin_iter.down()

        sub_fg_tot = bin_iter.get_last_save()
        if sub_fg_tot is None:
            raise ValueError('Cannot draw substrate that fit in width: %d' % well_width)

        # compute horizontal offset
        sub_width = self._layout_info.get_total_width(sub_fg_tot) * sd_pitch
        wsub_pitch, hsub_pitch = self.grid.get_size_pitch(hm_layer, unit_mode=True)
        nx_pitch = wtot // wsub_pitch
        nsub_pitch = sub_width // wsub_pitch
        x0 = (nx_pitch - nsub_pitch) // 2 * wsub_pitch

        # create substrate
        self._num_fingers = sub_fg_tot
        params = dict(
            lch=lch,
            w=w,
            sub_type=sub_type,
            threshold=threshold,
            fg=sub_fg_tot,
            end_mode=sub_end_mode & 3,
            is_passive=is_passive,
            top_layer=hm_layer,
        )
        sub_master = self.new_template(params=params, temp_cls=AnalogSubstrate)
        edge_layout_info = sub_master.get_edge_layout_info()
        edge_params = dict(
            top_layer=hm_layer,
            is_end=True,
            guard_ring_nf=0,
            name_id=sub_master.get_layout_basename(),
            layout_info=edge_layout_info,
        )
        edge_master = self.new_template(params=edge_params, temp_cls=AnalogEdge)

        # find substrate height and set size
        hsub = sub_master.prim_bound_box.height_unit
        self.size = parent_grid.get_size_tuple(top_layer, wtot, hsub, round_up=True, unit_mode=True)
        # add cell boundary
        self.add_cell_boundary(self.bound_box)
        # find substrate Y offset to center it in the middle.
        sub_ny = hsub // hsub_pitch
        tot_ny = self.bound_box.height_unit // hsub_pitch
        y0 = (tot_ny - sub_ny) // 2 * hsub_pitch
        # add substrate and edge at the right locations
        loc = x0, y0
        instl = self.add_instance(edge_master, inst_name='XLE', loc=loc, unit_mode=True)
        loc = instl.array_box.right_unit, y0
        insts = self.add_instance(sub_master, inst_name='XSUB', loc=loc, unit_mode=True)
        loc = insts.array_box.right_unit + edge_master.array_box.right_unit, y0
        instr = self.add_instance(edge_master, inst_name='XRE', loc=loc, orient='MY', unit_mode=True)

        self.array_box = instl.array_box.merge(instr.array_box)
        # add well layer
        well_box = insts.translate_master_box(sub_master.get_well_box())
        well_xl = wtot // 2 - well_width // 2
        well_xr = well_xl + well_width
        well_box = well_box.extend(x=well_xl, unit_mode=True).extend(x=well_xr, unit_mode=True)
        if well_end_mode % 2 == 1:
            well_box = well_box.extend(y=0, unit_mode=True)
        if well_end_mode // 2 == 1:
            well_box = well_box.extend(y=self.bound_box.top_unit, unit_mode=True)

        self.add_well_geometry(sub_type, well_box)

        # find the first horizontal track index inside the array box
        hm_mid = self.grid.coord_to_nearest_track(hm_layer, self.array_box.yc_unit, mode=0,
                                                  half_track=True, unit_mode=True)
        # connect to horizontal metal layer.
        hm_pitch = self.grid.get_track_pitch(hm_layer, unit_mode=True)
        ntr = self.array_box.height_unit // hm_pitch  # type: int
        tr_width = self.grid.get_max_track_width(hm_layer, 1, ntr, half_end_space=False)
        track_id = TrackID(hm_layer, hm_mid, width=tr_width)
        port_name = 'VDD' if sub_type == 'ntap' else 'VSS'
        sub_wires = self.connect_to_tracks(insts.get_port(port_name).get_pins(hm_layer - 1), track_id)
        self.add_pin(port_name, sub_wires, show=show_pins)
