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

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
# noinspection PyUnresolvedReferences,PyCompatibility
from builtins import *

from typing import Dict, Any, Set

from bag.layout.template import TemplateBase, TemplateDB
from bag.layout.routing import TrackID
from bag.layout.util import BBox

from ..analog_core import AnalogBase
from ..passives.hp_filter import HighPassFilter


class DLevCap(TemplateBase):
    """An template for AC coupling clock arrays

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
            **kwargs :
                dictionary of optional parameters.  See documentation of
                :class:`bag.layout.template.TemplateBase` for details.
            """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        super(DLevCap, self).__init__(temp_db, lib_name, params, used_names, **kwargs)

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
            show_pins=True,
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
            num_layer='Number of cap layers.',
            bot_layer='cap bottom layer.',
            port_widths='port widths',
            io_width='input/output width.',
            io_space='input/output spacing.',
            width='cap width.',
            height='cap height.',
            space='cap spacing.',
            show_pins='True to draw pin layouts.',
        )

    def draw_layout(self):
        # type: () -> None
        self._draw_layout_helper(**self.params)

    def _draw_layout_helper(self, num_layer, bot_layer, port_widths, io_width,
                            io_space, width, height, space, show_pins):

        res = self.grid.resolution
        width = int(round(width / res))
        height = int(round(height / res))
        space = int(round(space / res))

        io_pitch = io_width + io_space
        io_layer = AnalogBase.get_mos_conn_layer(self.grid.tech_info) + 1
        vm_layer = io_layer + 1
        outp_tr = (io_width - 1) / 2
        inp_tr = outp_tr + io_pitch
        inn_tr = inp_tr + io_pitch
        outn_tr = inn_tr + io_pitch
        tr_list = [outp_tr, inp_tr, inn_tr, outn_tr]

        cap_yb = self.grid.get_wire_bounds(io_layer, outn_tr, width=io_width, unit_mode=True)[1]
        cap_yb += space

        # draw caps
        cap_bboxl = BBox(0, cap_yb, width, cap_yb + height, res, unit_mode=True)
        cap_bboxr = cap_bboxl.move_by(dx=width + space, unit_mode=True)
        capl_ports = self.add_mom_cap(cap_bboxl, bot_layer, num_layer, port_widths=port_widths)
        capr_ports = self.add_mom_cap(cap_bboxr, bot_layer, num_layer, port_widths=port_widths)
        # connect caps to dlev/summer inputs/outputs
        warr_list = [capl_ports[vm_layer][0], capl_ports[vm_layer][1],
                     capr_ports[vm_layer][0], capr_ports[vm_layer][1]]
        hwarr_list = self.connect_matching_tracks(warr_list, io_layer, tr_list, width=io_width)

        for name, warr in zip(('outp', 'inp', 'inn', 'outn'), hwarr_list):
            self.add_pin(name, warr, show=show_pins)

        # calculate size
        top_layer = bot_layer + num_layer - 1
        if self.grid.get_direction(top_layer) == 'x':
            yt = capr_ports[top_layer][1][0].get_bbox_array(self.grid).top_unit
            xr = capr_ports[top_layer - 1][1][0].get_bbox_array(self.grid).right_unit
        else:
            yt = capr_ports[top_layer - 1][1][0].get_bbox_array(self.grid).top_unit
            xr = capr_ports[top_layer][1][0].get_bbox_array(self.grid).right_unit

        w_blk, h_blk = self.grid.get_block_size(top_layer, unit_mode=True)
        nx = -(-xr // w_blk)
        ny = -(-yt // h_blk)
        self.size = top_layer, nx, ny
        self.array_box = BBox(0, 0, nx * w_blk, ny * h_blk, res, unit_mode=True)


class RXClkArray(TemplateBase):
    """An template for AC coupling clock arrays

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
        **kwargs :
            dictionary of optional parameters.  See documentation of
            :class:`bag.layout.template.TemplateBase` for details.
        """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        super(RXClkArray, self).__init__(temp_db, lib_name, params, used_names, **kwargs)

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
            show_pins=True,
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
            passive_params='High-pass filter passives parameters.',
            out_width='input/output track width.',
            in_width='input track width on upper layer.',
            clk_names='output clock names.',
            clk_locs='output clock locations.',
            parity='input/output clock parity.',
            show_pins='True to draw pin layouts.',
        )

    def draw_layout(self):
        # type: () -> None
        self._draw_layout_helper(**self.params)

    def _draw_layout_helper(self, passive_params, out_width, in_width, clk_names, clk_locs, parity, show_pins):
        hpf_params = passive_params.copy()
        hpf_params['show_pins'] = False

        # add high pass filters
        num_blocks = len(clk_names)
        hpf_master = self.new_template(params=hpf_params, temp_cls=HighPassFilter)
        blk_w = self.grid.get_size_dimension(hpf_master.size, unit_mode=True)[0]
        inst = self.add_instance(hpf_master, 'XHPF', nx=num_blocks, spx=blk_w, unit_mode=True)
        io_layer = inst.get_all_port_pins('in')[0].layer_id + 1

        num_tracks = self.grid.get_num_tracks(hpf_master.size, io_layer)
        ltr, rtr = self.grid.get_evenly_spaced_tracks(2, num_tracks, out_width, half_end_space=True)
        mtr = (ltr + rtr) / 2

        prefix = 'clkp' if parity == 1 else 'clkn'

        in_list = []
        for idx, out_name, out_loc in zip(range(num_blocks), clk_names, clk_locs):
            offset = num_tracks * idx
            iid = mtr + offset
            if out_loc == 0:
                oid = iid
            elif parity > 0:
                oid = ltr + offset
            else:
                oid = rtr + offset

            inwarr = inst.get_port('in', col=idx).get_pins()[0]
            outwarr = inst.get_port('out', col=idx).get_pins()[0]
            inwarr = self.connect_to_tracks(inwarr, TrackID(io_layer, iid, width=out_width), min_len_mode=0)
            outwarr = self.connect_to_tracks(outwarr, TrackID(io_layer, oid, width=out_width), min_len_mode=-1)
            in_list.append(inwarr)
            self.add_pin(prefix + '_' + out_name, outwarr, show=show_pins)
            self.reexport(inst.get_port('bias', col=idx), net_name='bias_' + out_name, show=show_pins)

        iid = self.grid.coord_to_nearest_track(io_layer + 1, in_list[0].middle)
        inwarr = self.connect_to_tracks(in_list, TrackID(io_layer + 1, iid, width=in_width), min_len_mode=0)
        self.add_pin(prefix, inwarr, show=show_pins)
