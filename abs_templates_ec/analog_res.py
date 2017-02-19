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


"""This module defines abstract analog mosfet template classes.
"""
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
# noinspection PyUnresolvedReferences,PyCompatibility
from builtins import *
from future.utils import with_metaclass

import abc
from bag import float_to_si_string
from bag.layout.util import BBox
from bag.layout.routing import TrackID
from bag.layout.template import MicroTemplate


class AnalogResCore(with_metaclass(abc.ABCMeta, MicroTemplate)):
    """An abstract template for analog resistors array core.

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
        MicroTemplate.__init__(self, temp_db, lib_name, params, used_names, **kwargs)

    @classmethod
    @abc.abstractmethod
    def use_parity(cls):
        """Returns True if parity changes resistor core layout."""
        return False

    @classmethod
    @abc.abstractmethod
    def port_layer_id(cls):
        """Returns the resistor port layer ID.

        Bottom port layer must be horizontal.
        """
        return -1

    @classmethod
    @abc.abstractmethod
    def array_port_layer_id(cls):
        """Returns the resistor array top horizontal metal port layer ID.

        Bottom port layer must be horizontal.
        """
        return -1

    @classmethod
    def get_default_param_values(cls):
        """Returns a dictionary containing default parameter values.

        Override this method to define default parameter values.  As good practice,
        you should avoid defining default values for technology-dependent parameters
        (such as channel length, transistor width, etc.), but only define default
        values for technology-independent parameters (such as number of tracks).

        Returns
        -------
        default_params : dict[str, any]
            dictionary of default parameter values.
        """
        return dict(
            x_tracks_min=1,
            y_tracks_min=1,
            res_type='reference',
            parity=0,
            sub_type='ntap',
            em_specs={},
        )

    @classmethod
    def get_params_info(cls):
        """Returns a dictionary containing parameter descriptions.

        Override this method to return a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : dict[str, str]
            dictionary from parameter name to description.
        """
        return dict(
            l='unit resistor length, in meters.',
            w='unit resistor width, in meters.',
            x_tracks_min='Minimum number of horizontal tracks per block.',
            y_tracks_min='Minimum number of vertical tracks per block.',
            parity='the parity of this resistor core.  Either 0 or 1.',
            sub_type='the substrate type.',
            res_type='the resistor type.',
            em_specs='resistor EM spec specifications.',
        )

    @abc.abstractmethod
    def get_xy_tracks(self):
        """Returns the number of top level horizontal/vertical tracks in this template.

        Note: this method must work before draw_layout() is called.

        Returns
        -------
        num_x_tracks : int
            number of top level horizontal tracks in this template.
        num_y_tracks : int
            number of top level vertical tracks in this template.
        """
        return 1, 1

    @abc.abstractmethod
    def get_hv_tracks(self):
        """Returns the number of lower level horizontal/vertical tracks in this template.

        Returns
        -------
        num_h_tracks : int
            number of lower level horizontal tracks in this template.
        num_v_tracks : int
            number of lower level vertical tracks in this template.
        """
        return 1, 1

    @abc.abstractmethod
    def get_hve_tracks(self):
        """Returns the number of lower level horizontal/vertical tracks in the edge templates.

        Returns
        -------
        num_h_tracks : int
            number of lower level horizontal tracks in the bottom edge template.
        num_v_tracks : int
            number of lower level vertical tracks in the left edge template.
        """
        return 1, 1

    @abc.abstractmethod
    def get_hv_width(self):
        """Returns the lower level horizontal/vertical track widths.

        Returns
        -------
        h_width_ntr : int
            lower level horizontal track width in number of tracks.
        v_width_ntr : int
            lower level vertical track width in number of tracks.
        """
        return 1, 1

    # TODO: add get_xy_width, and make resistor block interpret x/y_tracks_min in widths

    @abc.abstractmethod
    def port_locations(self):
        """Returns the port locations of this resistor.

        Returns
        -------
        top_pin : Tuple[str, :class:`~bag.layout.util.BBox`]
            the top pin represented as (layer, bbox) tuple.
        bot_pin : Tuple[str, :class:`~bag.layout.util.BBox`]
            the bottom pin represented as (layer, bbox) tuple.
        """
        return None

    def get_layout_basename(self):
        """Returns the base name for this template.

        Returns
        -------
        base_name : str
            the base name of this template.
        """

        ntrx, ntry = self.get_xy_tracks()
        l_str = float_to_si_string(self.params['l'])
        w_str = float_to_si_string(self.params['w'])
        main = 'rescore_%s_%s_l%s_w%s_xtr%d_ytr%d' % (self.params['res_type'],
                                                      self.params['sub_type'],
                                                      l_str, w_str, ntrx, ntry)
        if self.use_parity():
            main += '_par%d' % self.params['parity']

        return main

    def compute_unique_key(self):
        return self.get_layout_basename()


# noinspection PyAbstractClass
class AnalogResLREdge(with_metaclass(abc.ABCMeta, MicroTemplate)):
    """An abstract template for analog resistors array left/right edge.

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
        MicroTemplate.__init__(self, temp_db, lib_name, params, used_names, **kwargs)

    @classmethod
    def get_default_param_values(cls):
        """Returns a dictionary containing default parameter values.

        Override this method to define default parameter values.  As good practice,
        you should avoid defining default values for technology-dependent parameters
        (such as channel length, transistor width, etc.), but only define default
        values for technology-independent parameters (such as number of tracks).

        Returns
        -------
        default_params : dict[str, any]
            dictionary of default parameter values.
        """
        return dict(
            x_tracks_min=1,
            y_tracks_min=1,
            parity=0,
            sub_type='ntap',
            res_type='reference',
            em_specs={},
        )

    @classmethod
    def get_params_info(cls):
        """Returns a dictionary containing parameter descriptions.

        Override this method to return a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : dict[str, str]
            dictionary from parameter name to description.
        """
        return dict(
            l='unit resistor length, in meters.',
            w='unit resistor width, in meters.',
            x_tracks_min='Minimum number of horizontal tracks per block.',
            y_tracks_min='Minimum number of vertical tracks per block.',
            parity='the parity of this resistor core.  Either 0 or 1.',
            sub_type='the substrate type.',
            res_type='the resistor type.',
            em_specs='resistor EM spec specifications.',
        )

    @abc.abstractmethod
    def get_xy_tracks(self):
        """Returns the number of vertical/horizontal tracks in this template.

        Note: this method must work before draw_layout() is called.

        Returns
        -------
        num_x_tracks : int
            number of horizontal tracks in this template.
        num_y_tracks : int
            number of vertical tracks in this template.
        """
        return 1, 1

    def get_layout_basename(self):
        """Returns the base name for this template.

        Returns
        -------
        base_name : str
            the base name of this template.
        """
        tech_params = self.grid.tech_info.tech_params
        res_cls = tech_params['layout']['res_core_template']

        l_str = float_to_si_string(self.params['l'])
        w_str = float_to_si_string(self.params['w'])
        ntrx, ntry = self.get_xy_tracks()
        main = 'resedgelr_%s_%s_l%s_w%s_xtr%d_ytr%d' % (self.params['res_type'],
                                                        self.params['sub_type'],
                                                        l_str, w_str, ntrx, ntry)
        if res_cls.use_parity():
            main += '_par%d' % self.params['parity']

        return main

    def compute_unique_key(self):
        return self.get_layout_basename()


# noinspection PyAbstractClass
class AnalogResTBEdge(with_metaclass(abc.ABCMeta, MicroTemplate)):
    """An abstract template for analog resistors array left/right edge.

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
        MicroTemplate.__init__(self, temp_db, lib_name, params, used_names, **kwargs)

    @classmethod
    def get_default_param_values(cls):
        """Returns a dictionary containing default parameter values.

        Override this method to define default parameter values.  As good practice,
        you should avoid defining default values for technology-dependent parameters
        (such as channel length, transistor width, etc.), but only define default
        values for technology-independent parameters (such as number of tracks).

        Returns
        -------
        default_params : dict[str, any]
            dictionary of default parameter values.
        """
        return dict(
            x_tracks_min=1,
            y_tracks_min=1,
            parity=0,
            sub_type='ntap',
            res_type='reference',
            em_specs={},
        )

    @classmethod
    def get_params_info(cls):
        """Returns a dictionary containing parameter descriptions.

        Override this method to return a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : dict[str, str]
            dictionary from parameter name to description.
        """
        return dict(
            l='unit resistor length, in meters.',
            w='unit resistor width, in meters.',
            x_tracks_min='Minimum number of horizontal tracks per block.',
            y_tracks_min='Minimum number of vertical tracks per block.',
            parity='the parity of this resistor core.  Either 0 or 1.',
            sub_type='the substrate type.',
            res_type='the resistor type.',
            em_specs='resistor EM specifications.',
        )

    @abc.abstractmethod
    def get_xy_tracks(self):
        """Returns the number of vertical/horizontal tracks in this template.

        Note: this method must work before draw_layout() is called.

        Returns
        -------
        num_x_tracks : int
            number of horizontal tracks in this template.
        num_y_tracks : int
            number of vertical tracks in this template.
        """
        return 1, 1

    def get_layout_basename(self):
        """Returns the base name for this template.

        Returns
        -------
        base_name : str
            the base name of this template.
        """
        tech_params = self.grid.tech_info.tech_params
        res_cls = tech_params['layout']['res_core_template']

        l_str = float_to_si_string(self.params['l'])
        w_str = float_to_si_string(self.params['w'])
        ntrx, ntry = self.get_xy_tracks()
        main = 'resedgetb_%s_%s_l%s_w%s_xtr%d_ytr%d' % (self.params['res_type'],
                                                        self.params['sub_type'],
                                                        l_str, w_str, ntrx, ntry)
        if res_cls.use_parity():
            main += '_par%d' % self.params['parity']

        return main

    def compute_unique_key(self):
        return self.get_layout_basename()


# noinspection PyAbstractClass
class AnalogResCorner(with_metaclass(abc.ABCMeta, MicroTemplate)):
    """An abstract template for analog resistors array left/right edge.

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
        MicroTemplate.__init__(self, temp_db, lib_name, params, used_names, **kwargs)

    @classmethod
    def get_default_param_values(cls):
        """Returns a dictionary containing default parameter values.

        Override this method to define default parameter values.  As good practice,
        you should avoid defining default values for technology-dependent parameters
        (such as channel length, transistor width, etc.), but only define default
        values for technology-independent parameters (such as number of tracks).

        Returns
        -------
        default_params : dict[str, any]
            dictionary of default parameter values.
        """
        return dict(
            x_tracks_min=1,
            y_tracks_min=1,
            parity=0,
            sub_type='ntap',
            res_type='reference',
            em_specs={},
        )

    @classmethod
    def get_params_info(cls):
        """Returns a dictionary containing parameter descriptions.

        Override this method to return a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : dict[str, str]
            dictionary from parameter name to description.
        """
        return dict(
            l='unit resistor length, in meters.',
            w='unit resistor width, in meters.',
            x_tracks_min='Minimum number of horizontal tracks per block.',
            y_tracks_min='Minimum number of vertical tracks per block.',
            parity='the parity of this resistor core.  Either 0 or 1.',
            sub_type='the substrate type.',
            res_type='the resistor type.',
            em_specs='resistor EM specifications.',
        )

    @abc.abstractmethod
    def get_xy_tracks(self):
        """Returns the number of vertical/horizontal tracks in this template.

        Note: this method must work before draw_layout() is called.

        Returns
        -------
        num_x_tracks : int
            number of horizontal tracks in this template.
        num_y_tracks : int
            number of vertical tracks in this template.
        """
        return 1, 1

    def get_layout_basename(self):
        """Returns the base name for this template.

        Returns
        -------
        base_name : str
            the base name of this template.
        """
        tech_params = self.grid.tech_info.tech_params
        res_cls = tech_params['layout']['res_core_template']

        l_str = float_to_si_string(self.params['l'])
        w_str = float_to_si_string(self.params['w'])
        ntrx, ntry = self.get_xy_tracks()
        main = 'rescorner_%s_%s_l%s_w%s_xtr%d_ytr%d' % (self.params['res_type'],
                                                        self.params['sub_type'],
                                                        l_str, w_str, ntrx, ntry)
        if res_cls.use_parity():
            main += '_par%d' % self.params['parity']

        return main

    def compute_unique_key(self):
        return self.get_layout_basename()


# TODO: modify implementation after get_xy_width() is implemented.
# noinspection PyAbstractClass
class ResArrayBase(with_metaclass(abc.ABCMeta, MicroTemplate)):
    """An abstract template that draws analog resistors array and connections.

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
        MicroTemplate.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        tech_params = self.grid.tech_info.tech_params
        self._core_cls = tech_params['layout']['res_core_template']
        self._edgelr_cls = tech_params['layout']['res_edgelr_template']
        self._edgetb_cls = tech_params['layout']['res_edgetb_template']
        self._corner_cls = tech_params['layout']['res_corner_template']
        self._use_parity = self._core_cls.use_parity()
        self._port_dict = {}
        self._core_offset = None
        self._core_pitch = None
        self._num_h_tracks = None
        self._num_v_tracks = None
        self._num_he_tracks = None
        self._num_ve_tracks = None
        self._hm_width = None
        self._vm_width = None
        self._hm_layer = self._core_cls.port_layer_id() + 1

    @property
    def num_h_tracks(self):
        return self._num_h_tracks

    @property
    def num_v_tracks(self):
        return self._num_v_tracks

    def connect_lr(self, row_idx, left_col_idx, pos):
        """Connect the resistor at the given coordinate to the resistor on its right.

        Parameters
        ----------
        row_idx : int
            the resistor row index.  0 is the bottom row.
        left_col_idx : int
            the left resistor column index.  0 is the left-most column.
        pos : int
            the port position, 0 for bottom port, 1 for top port.

        Returns
        -------
        warr : :class:`~bag.layout.routing.WireArray`
            the lower level horizontal track drawn to connect the resistors.
        """
        if pos != 0 and pos != 1:
            raise ValueError('pos = %s must be either 0 or 1' % repr(pos))
        par0 = (row_idx + left_col_idx) % 2
        lay0, port_bbox = self._port_dict[par0][pos]
        lay1, _ = self._port_dict[1 - par0][pos]
        hm_tr_sp = self.grid.get_num_space_tracks(self._hm_layer, self._hm_width, half_space=False)

        # step 1: determinal horizontal track index.
        if pos == 0:
            # find first track below bottom port
            tr_idx = self.grid.find_next_track(self._hm_layer, port_bbox.top, tr_width=self._hm_width,
                                               half_track=True, mode=-1)
            # max with minimum legal track index based on spacing to block below
            tr_idx = max(tr_idx, (self._hm_width + hm_tr_sp - 1) / 2.0)
        else:
            # find first track above top port
            tr_idx = self.grid.find_next_track(self._hm_layer, port_bbox.bottom, tr_width=self._hm_width,
                                               half_track=True, mode=1)
            # min with maximum legal track index based on spacing to block above
            tr_idx = min(tr_idx, self._num_h_tracks - 1 - (self._hm_width + hm_tr_sp - 1) / 2.0)

        # step 2: create TrackID
        tr_idx += row_idx * self._num_h_tracks + self._num_he_tracks
        tid = TrackID(self._hm_layer, tr_idx, width=self._hm_width)

        # step 2: connect ports to track
        dx = self._core_offset[0] + self._core_pitch[0] * left_col_idx
        dy = self._core_offset[1] + self._core_pitch[1] * row_idx
        warr0 = self.connect_bbox_to_tracks(lay0, port_bbox.move_by(dx, dy), tid)
        warr1 = self.connect_bbox_to_tracks(lay1, port_bbox.move_by(dx + self._core_pitch[0], dy), tid)

        result = self.connect_wires([warr0, warr1])[0]  # get only element from list
        return result

    def draw_array(self, l, w, nx=1, ny=1, x_tracks_min=1, y_tracks_min=1,
                   sub_type='ntap', res_type='reference', em_specs=None):
        """Draws the resistor array.

        Parameters
        ----------
        l : float
            unit resistor length, in meters.
        w : float
            unit resistor width, in meters.
        nx : int
            number of resistors in a row.
        ny : int
            number of resistors in a column.
        x_tracks_min : int
            minimum number of horizontal tracks per resistor unit cell.
        y_tracks_min : int
            minimum number of vertical tracks per resistor unit cell.
        sub_type : string
            the substrate type.  Either 'ptap' or 'ntap'.
        res_type : string
            the resistor type.
        em_specs : Dict[str, any] or None
            resistor EM specifications dictionary.
        """
        # add resistor array layers to RoutingGrid
        self.grid = self.grid.copy()
        grid_layers = self.grid.tech_info.tech_params['layout']['analog_res']['grid_layers']
        for lay_id, tr_w, tr_sp, tr_dir in grid_layers:
            self.grid.add_new_layer(lay_id, tr_sp, tr_w, tr_dir)
        self.grid.update_block_pitch()

        layout_params = dict(
            l=l,
            w=w,
            x_tracks_min=x_tracks_min,
            y_tracks_min=y_tracks_min,
            sub_type=sub_type,
            res_type=res_type,
            parity=0,
            em_specs=em_specs or {},
        )
        # create BL corner
        master = self.new_template(params=layout_params, temp_cls=self._corner_cls)
        self.add_instance(master)
        w_edge_lr = master.array_box.width
        h_edge_tb = master.array_box.height

        # create bottom edge
        master = self._add_blk(self._edgetb_cls, layout_params, (w_edge_lr, 0.0),
                               'R0', nx, 1, 1)
        w_core = master.array_box.width

        # create BR corner
        layout_params['parity'] = (nx + 1) % 2
        master = self.new_template(params=layout_params, temp_cls=self._corner_cls)
        inst = self.add_instance(master, orient='MY')
        inst.move_by(dx=w_edge_lr + nx * w_core - inst.array_box.left)

        # create left edge
        master = self._add_blk(self._edgelr_cls, layout_params, (0.0, h_edge_tb),
                               'R0', 1, ny, 1)
        h_core = master.array_box.height

        # create TL corner
        layout_params['parity'] = (ny + 1) % 2
        master = self.new_template(params=layout_params, temp_cls=self._corner_cls)
        inst = self.add_instance(master, orient='MX')
        inst.move_by(dy=h_edge_tb + ny * h_core - inst.array_box.bottom)

        # create core
        self._core_offset = (w_edge_lr, h_edge_tb)
        self._core_pitch = (w_core, h_core)
        self._add_blk(self._core_cls, layout_params, self._core_offset,
                      'R0', nx, ny, 0)

        # create top edge
        loc = (w_edge_lr, 2 * h_edge_tb + ny * h_core)
        self._add_blk(self._edgetb_cls, layout_params, loc, 'MX', nx, 1, ny % 2)

        # create right edge
        loc = (2 * w_edge_lr + nx * w_core, h_edge_tb)
        self._add_blk(self._edgelr_cls, layout_params, loc, 'MY', 1, ny, nx % 2)

        # create TR corner
        self.array_box = BBox(0.0, 0.0, 2 * w_edge_lr + nx * w_core, 2 * h_edge_tb + ny * h_core,
                              self.grid.resolution)
        layout_params['parity'] = (nx + ny) % 2
        master = self.new_template(params=layout_params, temp_cls=self._corner_cls)
        self.add_instance(master, loc=(self.array_box.right, self.array_box.top),
                          orient='R180')

    def _add_blk(self, temp_cls, params, loc, orient, nx, ny, par0):
        params['parity'] = par0
        master0 = self.new_template(params=params, temp_cls=temp_cls)
        if isinstance(master0, AnalogResCore):
            self._port_dict[par0] = master0.port_locations()
            if not self._use_parity:
                self._port_dict[1 - par0] = master0.port_locations()
            self._num_h_tracks, self._num_v_tracks = master0.get_hv_tracks()
            self._num_he_tracks, self._num_ve_tracks = master0.get_hve_tracks()
            self._hm_width, self._vm_width = master0.get_hv_width()

        spx = master0.array_box.width
        spy = master0.array_box.height
        if not self._use_parity:
            self.add_instance(master0, loc=loc, nx=nx, ny=ny, spx=spx, spy=spy,
                              orient=orient)
        else:
            # add current parity
            nx0 = (nx + 1) // 2
            ny0 = (ny + 1) // 2
            self.add_instance(master0, loc=loc, nx=nx0, ny=ny0, spx=spx * 2, spy=spy * 2,
                              orient=orient)
            nx0 = nx // 2
            ny0 = ny // 2
            if nx0 > 0 and ny0 > 0:
                self.add_instance(master0, loc=(loc[0] + spx, loc[1] + spy),
                                  nx=nx0, ny=ny0, spx=spx * 2, spy=spy * 2, orient=orient)

            # add opposite parity
            params['parity'] = 1 - par0
            master1 = self.new_template(params=params, temp_cls=temp_cls)
            if isinstance(master1, AnalogResCore):
                self._port_dict[1 - par0] = master1.port_locations()
            nx1 = nx // 2
            ny1 = (ny + 1) // 2
            if nx1 > 0 and ny1 > 0:
                self.add_instance(master1, loc=(loc[0] + spx, loc[1]),
                                  nx=nx1, ny=ny1, spx=spx * 2, spy=spy * 2, orient=orient)
            nx1 = (nx + 1) // 2
            ny1 = ny // 2
            if nx1 > 0 and ny1 > 0:
                self.add_instance(master1, loc=(loc[0], loc[1] + spy),
                                  nx=nx1, ny=ny1, spx=spx * 2, spy=spy * 2, orient=orient)

        return master0


class ResArrayTest(ResArrayBase):
    """An abstract template that draws analog resistors array and connections.

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
        ResArrayBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)

    @classmethod
    def get_default_param_values(cls):
        """Returns a dictionary containing default parameter values.

        Override this method to define default parameter values.  As good practice,
        you should avoid defining default values for technology-dependent parameters
        (such as channel length, transistor width, etc.), but only define default
        values for technology-independent parameters (such as number of tracks).

        Returns
        -------
        default_params : dict[str, any]
            dictionary of default parameter values.
        """
        return dict(
            nx=1,
            ny=1,
            x_tracks_min=1,
            y_tracks_min=1,
            sub_type='ntap',
            res_type='reference',
            em_specs={},
        )

    @classmethod
    def get_params_info(cls):
        """Returns a dictionary containing parameter descriptions.

        Override this method to return a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : dict[str, str]
            dictionary from parameter name to description.
        """
        return dict(
            l='unit resistor length, in meters.',
            w='unit resistor width, in meters.',
            nx='number of resistors in a row.',
            ny='number of resistors in a column.',
            x_tracks_min='Minimum number of horizontal tracks per block.',
            y_tracks_min='Minimum number of vertical tracks per block.',
            sub_type='the substrate type.',
            res_type='the resistor type.',
            em_specs='resistor EM specifications.',
        )

    def draw_layout(self):
        ny = self.params['ny']
        self.draw_array(**self.params)
        for idx in range(ny):
            self.connect_lr(idx, 0, 1)
