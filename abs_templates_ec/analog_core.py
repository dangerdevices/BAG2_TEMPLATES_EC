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
from itertools import chain, repeat
from typing import List

from bag.util.interval import IntervalSet
from bag.layout.template import MicroTemplate
from bag.layout.routing import TrackID
from .analog_mos import AnalogMosBase, AnalogSubstrate, AnalogMosConn
from future.utils import with_metaclass


def _flip_ud(orient):
    """Returns the new orientation after flipping the given orientation in up-down direction."""
    if orient == 'R0':
        return 'MX'
    elif orient == 'MX':
        return 'R0'
    elif orient == 'MY':
        return 'R180'
    elif orient == 'R180':
        return 'MY'
    else:
        raise ValueError('Unknown orientation: %s' % orient)


def _subtract(intv_list1, intv_list2):
    """Substrate intv_list2 from intv_list1.

    intv_list2 must be a subset of intv_list1.  Used by dummy connection calculation.

    Parameters
    ----------
    intv_list1 : list[(int, int)] or None
        first list of intervals.
    intv_list2 : list[(int, int)] or None
        second list of intervals.

    Returns
    -------
    result : list[(int, int)]
        the result of substracting the intervals in intv_list2 from intv_list1.
    """
    idx1 = idx2 = 0
    result = []
    intv1 = intv_list1[idx1]
    while idx1 < len(intv_list1) and idx2 < len(intv_list2):
        intv2 = intv_list2[idx2]
        if intv2[1] < intv1[0]:
            # no overlap, retire intv2
            idx2 += 1
        elif intv1[1] < intv2[0]:
            # no overlap, retire intv1
            if intv1[1] - intv1[0] > 0:
                result.append(intv1)
            idx1 += 1
            if idx1 < len(intv_list1):
                intv1 = intv_list1[idx1]
        else:
            # overlap, substract and update intv1
            test = intv1[0], intv2[0]
            if test[1] - test[0] > 0:
                result.append(test)
            intv1 = (intv2[1], intv1[1])
            idx2 += 1
    return result


def _intersection(intv_list1, intv_list2):
    """Returns the intersection of two lists of intervals.

    If one of the lists is None, the other list is returned.

    Parameters
    ----------
    intv_list1 : list[(int, int)] or None
        first list of intervals.
    intv_list2 : list[(int, int)] or None
        second list of intervals.

    Returns
    -------
    result : list[(int, int)]
        the intersection of the two lists of intervals.
    """
    if intv_list1 is None:
        return list(intv_list2)
    if intv_list2 is None:
        return list(intv_list1)

    idx1 = idx2 = 0
    result = []
    while idx1 < len(intv_list1) and idx2 < len(intv_list2):
        intv1 = intv_list1[idx1]
        intv2 = intv_list2[idx2]
        test = (max(intv1[0], intv2[0]), min(intv1[1], intv2[1]))
        if test[1] - test[0] > 0:
            result.append(test)
        if intv1[1] < intv2[1]:
            idx1 += 1
        elif intv2[1] < intv1[1]:
            idx2 += 1
        else:
            idx1 += 1
            idx2 += 1

    return result


def _get_dummy_connections(intv_set_list):
    """For each row of transistors, figure out all possible substrate connection locations.

    Parameters
    ----------
    intv_set_list : list[bag.util.interval.IntervalSet]
        a list of dummy finger intervals.  index 0 is the row closest to substrate.

    Returns
    -------
    conn_list : list[list[(int, int)]]
        a list of list of intervals.  conn_list[x] contains the finger intervals where
        you can connect exactly x+1 dummies vertically to substrate.
    """
    # populate conn_list
    # conn_list[x] contains intervals where you can connect x+1 or more dummies vertically.
    conn_list = []
    prev_intv_list = None
    for intv_set in intv_set_list:
        cur_intv_list = list(intv_set.intervals())
        conn = _intersection(cur_intv_list, prev_intv_list)
        conn_list.append(conn)
        prev_intv_list = conn

    # subtract adjacent conn_list elements
    # make it so conn_list[x] contains intervals where you can connect exactly x+1 dummies vertically
    for idx in range(len(conn_list) - 1):
        cur_conn, next_conn = conn_list[idx], conn_list[idx + 1]
        conn_list[idx] = _subtract(cur_conn, next_conn)

    return conn_list


def _select_dummy_connections(conn_list, unconnected, all_conn_list):
    """Helper method for selecting dummy connections locations.

    First, look at the connections that connect the most rows of dummy.  Try to use
    as many of these connections as possible while making sure they at least connect one
    unconnected dummy.  When done, repeat on connections that connect fewer rows.

    Parameters
    ----------
    conn_list : list[list[(int, int)]]
        a list of list of intervals.  conn_list[x] contains the finger intervals where
        you can connect exactly x+1 dummies vertically to substrate.
    unconnected : list[bag.util.interval.IntervalSet]
        a list of unconnected dummy finger intervals.  index 0 is the row closest to substrate.
    all_conn_list : list[(int, int)]
        a list of dummy finger intervals where you can connect from bottom substrate to top substrate.

    Returns
    -------
    select_list : list[list[(int, int)]]
        a list of list of intervals.  select_list[x] contains the finger intervals to
        draw dummy connections for x+1 rows from substrate.
    gate_intv_set_list : list[bag.util.interval.IntervalSet]
        a list of IntervalSets.  gate_intv_set_list[x] contains the finger intervals to
        draw dummy gate connections.
    """
    if all_conn_list:
        select_list = [all_conn_list]
        gate_intv_set_list = [IntervalSet(intv_list=all_conn_list)]
    else:
        select_list = []
        gate_intv_set_list = []
    for idx in range(len(conn_list) - 1, -1, -1):
        conn_intvs = conn_list[idx]
        cur_select_list = []
        # select connections
        for intv in conn_intvs:
            select = False
            for j in range(idx + 1):
                dummy_intv_set = unconnected[j]
                if dummy_intv_set.has_overlap(intv):
                    select = True
                    break
            if select:
                cur_select_list.append(intv)
        # remove all dummies connected with selected connections
        for intv in cur_select_list:
            for j in range(idx + 1):
                unconnected[j].remove_all_overlaps(intv)

        # include in select_list
        select_list.insert(0, cur_select_list)
        # construct gate interval list.
        if not gate_intv_set_list:
            # all_conn_list must be empty.  Don't need to consider it.
            gate_intv_set_list.append(IntervalSet(intv_list=cur_select_list))
        else:
            gate_intv_set = gate_intv_set_list[0].copy()
            for intv in cur_select_list:
                if not gate_intv_set.add(intv):
                    # this should never happen.
                    raise Exception('Critical Error: report to developers.')
            gate_intv_set_list.insert(0, gate_intv_set)

    return select_list, gate_intv_set_list


# noinspection PyAbstractClass
class AnalogBase(with_metaclass(abc.ABCMeta, MicroTemplate)):
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
    temp_db : :class:`bag.layout.template.TemplateDB`
            the template database.
    lib_name : str
        the layout library name.
    params : dict[str, any]
        the parameter values.
    used_names : set[str]
        a set of already used cell names.
    kwargs : dict[str, any]
        dictionary of optional parameters.  See documentation of
        :class:`bag.layout.template.TemplateBase` for details.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # call base class constructor
        MicroTemplate.__init__(self, temp_db, lib_name, params, used_names, **kwargs)

        tech_params = self.grid.tech_info.tech_params
        self._mos_cls = tech_params['layout']['mos_template']
        self._mconn_cls = tech_params['layout']['mos_conn_template']
        self._sub_cls = tech_params['layout']['sub_template']
        self._sep_cls = tech_params['layout']['mos_sep_template']
        self._dum_cls = tech_params['layout']['mos_dummy_template']

        # get information from template classes
        self._min_fg_sep = self._sep_cls.get_min_fg()

        # initialize parameters
        self._lch = None
        self._orient_list = None
        self._w_list = None
        self._sd_list = None
        self._sd_pitch = None
        self._fg_tot = None
        self._gds_space = None
        self._n_intvs = None  # type: List[IntervalSet]
        self._p_intvs = None  # type: List[IntervalSet]
        self._num_tracks = None
        self._track_offsets = None
        self._ds_tr_indices = None
        self._ntap_list = None
        self._ptap_list = None
        self._ridx_lookup = None
        self._ds_dummy_list = None
        self._bot_lay_id = self._mos_cls.port_layer_id()
        self._dum_lay_id = self._dum_cls.port_layer_id()

    @property
    def mos_conn_layer(self):
        """Returns the MOSFET connection layer ID."""
        return self._bot_lay_id

    @property
    def dum_conn_layer(self):
        """REturns the dummy connection layer ID."""
        return self._dum_lay_id

    @property
    def min_fg_sep(self):
        """Returns the minimum number of separator fingers."""
        return self._min_fg_sep

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
            ntr = self._ds_tr_indices[row_idx] - self._gds_space
        else:
            row_offset = self._ds_tr_indices[row_idx]
            ntr = self._num_tracks[row_idx] - row_offset

        return ntr

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
        ntr = self.get_num_tracks(mos_type, row_idx, tr_type)
        row_idx = self._find_row_index(mos_type, row_idx)

        offset = self._track_offsets[row_idx]
        if tr_type == 'g':
            row_offset = 0
        else:
            row_offset = self._ds_tr_indices[row_idx]

        if tr_idx < 0 or tr_idx >= ntr:
            raise ValueError('track index = %d out of bounds: [0, %d)' % (tr_idx, ntr))

        if self._orient_list[row_idx] == 'R0':
            return tr_idx + offset + row_offset
        else:
            return offset + self._num_tracks[row_idx] - (row_offset + tr_idx) - 1

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
        return TrackID(self._bot_lay_id + 1, tid, width=width, num=num, pitch=pitch)

    def connect_to_substrate(self, sub_type, warr_list, inner=False):
        """Connect the given transistor wires to substrate.
        
        Parameters
        ----------
        sub_type : string
            substrate type.  Either 'ptap' or 'ntap'.
        warr_list : list[bag.layout.routing.WireArray]
            list of WireArrays to connect to supply.
        inner : bool
            True to connect to inner substrate.
        """
        wire_yb, wire_yt = None, None
        port_name = 'VDD' if sub_type == 'ntap' else 'VSS'

        # get wire upper/lower Y coordinate
        if sub_type == 'ptap':
            if inner:
                if len(self._ptap_list) != 2:
                    raise ValueError('Inner substrate does not exist.')
                port = self._ptap_list[1].get_port(port_name)
                wire_yt = port.get_bounding_box(self.grid, self._bot_lay_id).top
            else:
                port = self._ptap_list[0].get_port(port_name)
                wire_yb = port.get_bounding_box(self.grid, self._bot_lay_id).bottom
        elif sub_type == 'ntap':
            if inner:
                if len(self._ntap_list) != 2:
                    raise ValueError('Inner substrate does not exist.')
                port = self._ntap_list[0].get_port(port_name)
                wire_yb = port.get_bounding_box(self.grid, self._bot_lay_id).bottom
            else:
                port = self._ntap_list[-1].get_port(port_name)
                wire_yt = port.get_bounding_box(self.grid, self._bot_lay_id).top
        else:
            raise ValueError('Invalid substrate type: %s' % sub_type)

        self.connect_wires(warr_list, lower=wire_yb, upper=wire_yt)

    def _draw_dummy_sep_conn(self, mos_type, row_idx, start, stop, gate_intv_list):
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
        gate_intv_list : list[(int, int)]
            sorted list of gate intervals to connect gate to M2.
            for example, if gate_intv_list = [(2, 5)], then we will draw M2 connections
            between finger number 2 (inclusive) to finger number 5 (exclusive).

        Returns
        -------
        wires : list[:class:`~bag.layout.routing.WireArray`]
            the dummy/separator gate bus wires.
        """
        # get orientation, width, and source/drain center
        ridx = self._ridx_lookup[mos_type][row_idx]
        orient = self._orient_list[ridx]
        w = self._w_list[ridx]
        xc, yc = self._sd_list[ridx]
        fg = stop - start

        # setup parameter list
        params = dict(
            lch=self._lch,
            w=w,
            fg=fg,
        )

        # get template class and do class-dependent actions
        if start == 0:
            temp_cls = self._dum_cls
            # set conn_right flag for dummy
            params['conn_right'] = (stop == self._fg_tot)
        elif stop == self._fg_tot:
            temp_cls = self._dum_cls
            params['conn_right'] = False
            # reverse gate_intv_list to account for horizontal flip
            gate_intv_list = [(fg - eind, fg - sind) for sind, eind in gate_intv_list]
            # update orientation and source/drain center coordinate
            xc += self._fg_tot * self._sd_pitch
            if orient == 'R0':
                orient = 'MY'
            else:
                orient = 'R180'
        else:
            # check number of fingers meet minimum finger spec
            if fg < self.min_fg_sep:
                raise ValueError('Cannot draw separator with num fingers = %d < %d' % (fg, self.min_fg_sep))
            temp_cls = self._sep_cls
            xc += start * self._sd_pitch

        params['gate_intv_list'] = gate_intv_list

        conn_master = self.new_template(params=params, temp_cls=temp_cls)
        conn_inst = self.add_instance(conn_master, loc=(xc, yc), orient=orient)

        return conn_inst.get_port().get_pins(self._dum_lay_id)

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
        kwargs : dict[string, any]
            optional arguments for AnalogMosConn.
        Returns
        -------
        ports : dict[str, bag.layout.routing.WireArray]
            a dictionary of ports as WireArrays.  The keys are 'g', 'd', and 's'.
        """
        # mark transistors as connected
        if mos_type == 'pch':
            intv_set = self._p_intvs[row_idx]
        else:
            intv_set = self._n_intvs[row_idx]

        intv = col_idx, col_idx + fg
        if not intv_set.add(intv):
            msg = 'Cannot connect %s row %d [%d, %d); some are already connected.'
            raise ValueError(msg % (mos_type, row_idx, intv[0], intv[1]))

        ridx = self._ridx_lookup[mos_type][row_idx]
        orient = self._orient_list[ridx]
        is_ds_dummy = self._ds_dummy_list[ridx]
        w = self._w_list[ridx]
        xc, yc = self._sd_list[ridx]
        xc += col_idx * self._sd_pitch

        if orient == 'MX':
            # flip source/drain directions
            sdir = 2 - sdir
            ddir = 2 - ddir

        conn_params = dict(
            lch=self._lch,
            w=w,
            fg=fg,
            sdir=sdir,
            ddir=ddir,
            is_ds_dummy=is_ds_dummy,
        )
        conn_params.update(kwargs)

        conn_master = self.new_template(params=conn_params, temp_cls=self._mconn_cls)  # type: AnalogMosConn
        conn_inst = self.add_instance(conn_master, loc=(xc, yc), orient=orient)

        return {key: conn_inst.get_port(key).get_pins(self._bot_lay_id)
                for key in ['g', 'd', 's'] if conn_inst.has_port(key)}

    @staticmethod
    def get_prop_lists(mos_type, sub_w, w_list, th_list, g_tracks, ds_tracks, orientations, both_subs,
                       ds_dummy_list):
        """Helper method of draw_base"""
        if mos_type == 'nch':
            sub_type = 'ptap'
            default_orient = 'R0'
            del_idx = -1
            sub_name = 'XPTAP'
            mname = 'XMN%d'
        else:
            sub_type = 'ntap'
            default_orient = 'MX'
            del_idx = 0
            sub_name = 'XNTAP'
            mname = 'XMP%d'
        num = len(w_list)
        if num == 0:
            # return nothing
            return [], [], [], [], [], [], []

        # set default values
        g_tracks = g_tracks or [1] * num
        ds_tracks = ds_tracks or [1] * num
        orientations = orientations or [default_orient] * num
        ds_dummy_list = ds_dummy_list or [False] * num

        # error checking
        if len(g_tracks) != num:
            raise ValueError('gate tracks list length != %d' % num)
        if len(th_list) != num:
            raise ValueError('threshold list length != %d' % num)
        if len(ds_tracks) != num:
            raise ValueError('drain/source tracks list length != %d' % num)
        if len(orientations) != num:
            raise ValueError('orientation list length != %d' % num)
        if len(ds_dummy_list) != num:
            raise ValueError('drain/source dummy list length != %d' % num)

        # get property lists
        mtype_list = list(chain([sub_type], repeat(mos_type, num), [sub_type]))
        orient_list = list(chain(['R0'], orientations, ['MX']))
        w_list = list(chain([sub_w], w_list, [sub_w]))
        th_list = list(chain([th_list[0]], th_list, [th_list[-1]]))
        g_list = list(chain([0], g_tracks, [0]))
        ds_list = list(chain([0], ds_tracks, [0]))
        name_list = list(chain([sub_name + 'B'], ((mname % idx for idx in range(num))),
                               [sub_name + 'T']))
        ds_dummy_list = list(chain([False], ds_dummy_list, [False]))

        if not both_subs:
            # remove middle substrates
            del mtype_list[del_idx]
            del orient_list[del_idx]
            del w_list[del_idx]
            del th_list[del_idx]
            del g_list[del_idx]
            del ds_list[del_idx]
            del name_list[del_idx]
            del ds_dummy_list[del_idx]

        return mtype_list, orient_list, w_list, th_list, g_list, ds_list, name_list, ds_dummy_list

    def draw_base(self, lch, fg_tot, ptap_w, ntap_w,
                  nw_list, nth_list, pw_list, pth_list,
                  gds_space,
                  ng_tracks=None, nds_tracks=None,
                  pg_tracks=None, pds_tracks=None,
                  n_orientations=None, p_orientations=None,
                  guard_ring_nf=0,
                  n_ds_dummy=None, p_ds_dummy=None,
                  extra_vss_tracks=None, extra_vdd_tracks=None,
                  ):
        """Draw the analog base.

        This method must be called first.

        Parameters
        ----------
        lch : float
            the transistor channel length, in meters
        fg_tot : int
            total number of fingers for each row.
        ptap_w : int or float
            pwell substrate contact width.
        ntap_w : int or float
            nwell substrate contact width.
        gds_space : int
            number of tracks to reserve as space between gate and drain/source tracks.
        nw_list : list[int or float]
            a list of nmos width for each row, from bottom to top.
        nth_list: list[str]
            a list of nmos threshold flavor for each row, from bottom to top.
        pw_list : list[int or float]
            a list of pmos width for each row, from bottom to top.
        pth_list : list[str]
            a list of pmos threshold flavor for each row, from bottom to top.
        ng_tracks : list[int] or None
            number of nmos gate tracks per row, from bottom to top.  Defaults to 1.
        nds_tracks : list[int] or None
            number of nmos drain/source tracks per row, from bottom to top.  Defaults to 1.
        pg_tracks : list[int] or None
            number of pmos gate tracks per row, from bottom to top.  Defaults to 1.
        pds_tracks : list[int] or None
            number of pmos drain/source tracks per row, from bottom to top.  Defaults to 1.
        n_orientations : list[str] or None
            orientation of each nmos row. Defaults to all 'R0'.
        p_orientations : list[str] or None
            orientation of each pmos row.  Defaults to all 'MX'.
        guard_ring_nf : int
            width of guard ring in number of fingers.  0 to disable guard ring.
        n_ds_dummy : list[bool] or None
            is_ds_dummy flag for each nmos row.  Defaults to all False.
        p_ds_dummy : list[bool] or None
            is_ds_dummy flag for each pmos row.  Defaults to all False.
        extra_vss_tracks : list or None
            list of extra vss tracks, in format of (ridx, ds_type, tr_idx, tr_width).
            assume mos_type = 'nch'.
        extra_vdd_tracks : list or None
            list of extra vdd tracks, in format of (ridx, ds_type, tr_idx, tr_width),
            assume mos_type = 'pch'.
        Returns
        -------
        ptap_wire_arrs : list[:class:`~bag.layout.routing.WireArray`]
            list of P-tap substrate WireArrays.
        ntap_wire_arrs : list[:class:`~bag.layout.routing.WireArray`]
            list of N-tap substrate WireArrays.
        """
        numn = len(nw_list)
        nump = len(pw_list)
        extra_vss_tracks = extra_vss_tracks or []
        extra_vdd_tracks = extra_vdd_tracks or []

        # get sd_pitch and vertical metal layer track info
        self._lch = lch
        self._sd_pitch = self._mos_cls.get_sd_pitch(lch)
        vm_width = self._mos_cls.get_port_width(lch)
        vm_space = self._sd_pitch - vm_width
        dum_width = self._dum_cls.get_port_width(lch)
        dum_space = self._sd_pitch - dum_width

        # register new grid layers
        self.grid = self.grid.copy()
        self.grid.add_new_layer(self._bot_lay_id, vm_space, vm_width, 'y', share_track=True)
        self.grid.add_new_layer(self._dum_lay_id, dum_space, dum_width, 'y', share_track=True)

        # initialize private attributes.
        self._fg_tot = fg_tot
        self._sd_list = []
        self._num_tracks = []
        self._track_offsets = []
        self._ds_tr_indices = []
        self._gds_space = gds_space
        self._ntap_list = []
        self._ptap_list = []
        self._ridx_lookup = dict(nch=[], pch=[], ntap=[], ptap=[])
        self._n_intvs = [IntervalSet() for _ in range(numn)]
        self._p_intvs = [IntervalSet() for _ in range(nump)]

        # get property lists
        results = self.get_prop_lists('nch', ntap_w, nw_list, nth_list, ng_tracks, nds_tracks,
                                      n_orientations, guard_ring_nf > 0 or nump == 0,
                                      n_ds_dummy)
        ntype_list, norient_list, nw_list, nth_list, ng_list, nds_list, nname_list, n_ds_dummy_list = results
        results = self.get_prop_lists('pch', ptap_w, pw_list, pth_list, pg_tracks, pds_tracks,
                                      p_orientations, guard_ring_nf > 0 or numn == 0,
                                      p_ds_dummy)
        ptype_list, porient_list, pw_list, pth_list, pg_list, pds_list, pname_list, p_ds_dummy_list = results

        self._orient_list = norient_list + porient_list
        self._w_list = nw_list + pw_list
        self._ds_dummy_list = n_ds_dummy_list + p_ds_dummy_list
        type_list = ntype_list + ptype_list
        th_list = nth_list + pth_list
        g_list = ng_list + pg_list
        ds_list = nds_list + pds_list
        name_list = nname_list + pname_list

        # draw rows
        tot_array_box = None
        gr_vss_ports = []
        gr_vdd_ports = []
        for ridx, value in enumerate(zip(type_list, self._orient_list, self._w_list, th_list, g_list,
                                         ds_list, name_list, self._ds_dummy_list)):
            mtype, orient, w, thres, gntr, dntr, name, ds_dummy = value
            self._ridx_lookup[mtype].append(ridx)
            is_mos = (mtype == 'nch' or mtype == 'pch')
            if is_mos:
                # transistor
                mparams = dict(mos_type=mtype, threshold=thres, lch=lch, w=w, fg=fg_tot,
                               g_tracks=gntr, ds_tracks=dntr, gds_space=gds_space,
                               guard_ring_nf=guard_ring_nf, is_ds_dummy=ds_dummy, )
                mmaster = self.new_template(params=mparams, temp_cls=self._mos_cls)  # type: AnalogMosBase
            else:
                # substrate
                is_end = (ridx == 0 or ridx == (len(type_list) - 1))
                mparams = dict(sub_type=mtype, threshold=thres, lch=lch, w=w, fg=fg_tot,
                               guard_ring_nf=guard_ring_nf, is_end=is_end, ummy_only=not is_end, )
                mmaster = self.new_template(params=mparams, temp_cls=self._sub_cls)  # type: AnalogSubstrate

            # add and shift instance
            minst = self.add_instance(mmaster, inst_name=name, orient=orient)
            if tot_array_box is None:
                tot_array_box = minst.array_box
            else:
                minst.move_by(dy=tot_array_box.top - minst.array_box.bottom)
                tot_array_box = tot_array_box.merge(minst.array_box)

            # update track information
            if self._track_offsets:
                self._track_offsets.append(self._track_offsets[-1] + self._num_tracks[-1])
            else:
                self._track_offsets.append(0)
            self._num_tracks.append(mmaster.get_num_tracks())
            # update sd center location and ds track index information
            if is_mos:
                sd_loc = minst.translate_master_location(mmaster.get_left_sd_center())
                self._sd_list.append(sd_loc)
                self._ds_tr_indices.append(mmaster.get_ds_track_index())
            else:
                self._sd_list.append((None, None))
                self._ds_tr_indices.append(0)

            # append substrates to respective list
            if mtype == 'ptap':
                self._ptap_list.append(minst)
            elif mtype == 'ntap':
                self._ntap_list.append(minst)

            # add body pins to respective list
            if minst.has_port('b'):
                if mtype == 'ptap' or mtype == 'nch':
                    gr_vss_ports.append(minst.get_port('b'))
                else:
                    gr_vdd_ports.append(minst.get_port('b'))

        # connect body guard rings together
        for mos_type, gr_sup_ports, extra_tracks in [('nch', gr_vss_ports, extra_vss_tracks),
                                                     ('pch', gr_vdd_ports, extra_vdd_tracks)]:
            if not extra_tracks:
                warr_list = list(chain(*(port.get_pins(self._bot_lay_id) for port in gr_sup_ports)))
                self.connect_wires(warr_list)
            else:
                pass

        self.array_box = tot_array_box

        # connect substrates to horizontal tracks.
        if nump == 0:
            # connect both substrates if NMOS only
            ptap_wire_arrs = self._connect_substrate('ptap', self._ptap_list, list(range(len(self._ptap_list))))
        elif numn > 0:
            # only connect bottom substrate to upper level metal
            ptap_wire_arrs = self._connect_substrate('ptap', self._ptap_list[:1], [0])
        else:
            ptap_wire_arrs = []

        # similarly for PMOS substrate
        if numn == 0:
            ntap_wire_arrs = self._connect_substrate('ntap', self._ntap_list, list(range(len(self._ntap_list))))
        elif nump > 0:
            ntap_wire_arrs = self._connect_substrate('ntap', self._ntap_list[-1:], [len(self._ntap_list) - 1])
        else:
            ntap_wire_arrs = []

        return ptap_wire_arrs, ntap_wire_arrs

    def _connect_substrate(self, sub_type, sub_list, row_idx_list):
        """Connect all given substrates to horizontal tracks

        Parameters
        ----------
        sub_list :
            list of substrates to connect.  Each element is a tuple
            of row-index, master, and instance.

        Returns
        -------
        track_buses : list[bag.layout.routing.WireArray]
            list of substrate tracks buses.
        """
        port_name = 'VDD' if sub_type == 'ntap' else 'VSS'

        sub_warr_list = []
        for row_idx, subinst in zip(row_idx_list, sub_list):
            # Create substrate TrackID
            # substrate 1 from number of tracks to give some margin for transistor.
            ntr = self.get_num_tracks(sub_type, row_idx, 'ds')
            tr_idx1 = self.get_track_index(sub_type, row_idx, 'ds', 0)
            tr_idx2 = self.get_track_index(sub_type, row_idx, 'ds', ntr - 2)
            track_id = TrackID(self._bot_lay_id + 1, min(tr_idx1, tr_idx2), 1, num=ntr - 1, pitch=1)

            # get all wires to connect to supply.
            warr_iter_list = [subinst.get_port(port_name).get_pins(self._bot_lay_id)]
            if subinst.has_port('b'):
                warr_iter_list.append(subinst.get_port('b').get_pins(self._bot_lay_id))

            warr_list = list(chain(*warr_iter_list))
            track_warr = self.connect_to_tracks(warr_list, track_id)
            sub_warr_list.append(track_warr)

        return sub_warr_list

    def fill_dummy(self):
        """Draw dummy/separator on all unused transistors.

        This method should be called last.
        """
        # invert PMOS/NMOS IntervalSet to get unconnected dummies
        total_intv = (0, self._fg_tot)
        p_intvs = [intv_set.get_complement(total_intv) for intv_set in self._p_intvs]
        n_intvs = [intv_set.get_complement(total_intv) for intv_set in self._n_intvs]

        # connect NMOS dummies
        top_sub_inst = None
        if self._ptap_list:
            bot_sub_inst = self._ptap_list[0]
            if len(self._ptap_list) > 1:
                top_sub_inst = self._ptap_list[1]
            self._fill_dummy_helper('nch', n_intvs, bot_sub_inst, top_sub_inst, not self._ntap_list)

        # connect PMOS dummies
        bot_sub_inst = None
        if self._ntap_list:
            top_sub_inst = self._ntap_list[-1]
            if len(self._ntap_list) > 1:
                bot_sub_inst = self._ntap_list[0]
            self._fill_dummy_helper('pch', p_intvs, bot_sub_inst, top_sub_inst, not self._ptap_list)

    def _fill_dummy_helper(self, mos_type, intv_set_list, bot_sub_inst, top_sub_inst, export_both):

        num_rows = len(intv_set_list)
        bot_conn = top_conn = []

        num_sub = 0
        if bot_sub_inst is not None:
            num_sub += 1
            bot_conn = _get_dummy_connections(intv_set_list)
        if top_sub_inst is not None:
            num_sub += 1
            top_conn = _get_dummy_connections(list(reversed(intv_set_list)))

        # make list of unconnected interval sets.
        unconn_intv_set_list = [intv_set.copy() for intv_set in intv_set_list]

        if num_sub == 2:
            # we have both top and bottom substrate, so we can connect all dummies together
            all_conn_list = bot_conn[-1]
            del bot_conn[-1]
            del top_conn[-1]

            # remove dummies connected by connections in all_conn_list
            for all_conn_intv in all_conn_list:
                for intv_set in unconn_intv_set_list:  # type: IntervalSet
                    intv_set.remove_all_overlaps(all_conn_intv)
        else:
            all_conn_list = []

        if mos_type == 'nch':
            # for NMOS, prioritize connection to bottom substrate.
            port_name = 'VSS'
            bot_select, bot_gintv = _select_dummy_connections(bot_conn, unconn_intv_set_list, all_conn_list)
            top_select, top_gintv = _select_dummy_connections(top_conn, unconn_intv_set_list, all_conn_list)
            if not export_both and top_sub_inst is not None:
                # change inner substrate port exports.
                top_sub_inst.new_master_with(port_intv_list=list(top_gintv[0].intervals()),
                                             port_mode='d')
        else:
            # for PMOS, prioritize connection to top substrate.
            port_name = 'VDD'
            top_select, top_gintv = _select_dummy_connections(top_conn, unconn_intv_set_list, all_conn_list)
            bot_select, bot_gintv = _select_dummy_connections(bot_conn, unconn_intv_set_list, all_conn_list)
            if not export_both and bot_sub_inst is not None:
                # change inner substrate port exports.
                bot_sub_inst.new_master_with(port_intv_list=list(bot_gintv[0].intervals()),
                                             port_mode='d')

        # make list of dummy gate connection parameters
        dummy_gate_conns = {}
        all_conn_set = IntervalSet(intv_list=all_conn_list)
        for gintvs, sign in [(bot_gintv, 1), (top_gintv, -1)]:
            if gintvs:
                for distance in range(num_rows):
                    ridx = distance if sign > 0 else num_rows - 1 - distance
                    gate_intv_set = gintvs[distance]
                    for dummy_intv in intv_set_list[ridx]:
                        key = ridx, dummy_intv[0], dummy_intv[1]
                        overlaps = list(gate_intv_set.overlap_intervals(dummy_intv))
                        val_list = [0 if ovl_intv in all_conn_set else sign for ovl_intv in overlaps]
                        if key not in dummy_gate_conns:
                            dummy_gate_conns[key] = IntervalSet(intv_list=overlaps, val_list=val_list)
                        else:
                            dummy_gate_set = dummy_gate_conns[key]  # type: IntervalSet
                            for fg_intv, ovl_val in zip(overlaps, val_list):
                                if not dummy_gate_set.has_overlap(fg_intv):
                                    dummy_gate_set.add(fg_intv, val=ovl_val)
                                else:
                                    # check that we don't have conflicting gate connections.
                                    for existing_intv, existing_val in dummy_gate_set.overlap_items(fg_intv):
                                        if existing_intv != fg_intv or existing_val != ovl_val:
                                            # this should never happen.
                                            raise Exception('Critical Error: report to developers.')

        wire_groups = {-1: [], 0: [], 1: []}
        for key, dummy_gate_set in dummy_gate_conns.items():
            ridx, start, stop = key
            if not dummy_gate_set:
                raise Exception('Dummy (%d, %d) at row %d unconnected.' % (start, stop, ridx))
            gate_intv_list = [(a - start, b - start) for a, b in dummy_gate_set]
            sub_val_iter = dummy_gate_set.values()
            gate_buses = self._draw_dummy_sep_conn(mos_type, ridx, start, stop, gate_intv_list)

            for box_arr, sub_val in zip(gate_buses, sub_val_iter):
                wire_groups[sub_val].append(box_arr)

        grid = self.grid
        sub_yb = sub_yt = None
        if bot_sub_inst is not None:
            sub_yb = bot_sub_inst.get_port(port_name).get_bounding_box(grid, self._dum_lay_id).bottom
        if top_sub_inst is not None:
            sub_yt = top_sub_inst.get_port(port_name).get_bounding_box(grid, self._dum_lay_id).top

        for sub_idx, wire_bus_list in wire_groups.items():
            wire_yb = sub_yb if sub_idx >= 0 else None
            wire_yt = sub_yt if sub_idx <= 0 else None

            self.connect_wires(wire_bus_list, lower=wire_yb, upper=wire_yt)
