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


"""This script tests that AnalogBase draws rows of transistors properly."""

from typing import Dict, Any, Set

import yaml
import math

from bag import BagProject
from bag.layout.routing import RoutingGrid, TrackID
from bag.layout.template import TemplateDB

from abs_templates_ec.laygo.core import LaygoBase
from abs_templates_ec.digital.core import DigitalBase


class StackDriver(LaygoBase):
    """A single diff amp.

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
        super(StackDriver, self).__init__(temp_db, lib_name, params, used_names, **kwargs)

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
            config='laygo configuration dictionary.',
            threshold='transistor threshold flavor.',
            num_seg='number of driver segments.',
            sup_width='width of supply and output wire.',
            show_pins='True to draw pin geometries.',
            w_p='pmos width.',
            w_n='nmos width.',
            parity='input gate track parity.',
            sig_space='minimum number of space tracks between signals.',
            guard_ring_nf='number of guard ring fingers.',
        )

    def draw_layout(self):
        """Draw the layout of a dynamic latch chain.
        """

        threshold = self.params['threshold']
        num_seg = self.params['num_seg']
        show_pins = self.params['show_pins']
        sup_width = self.params['sup_width']
        w_p = self.params['w_p']
        w_n = self.params['w_n']
        parity = self.params['parity']
        sig_space = self.params['sig_space']
        w_sub = self.params['config']['w_sub']
        guard_ring_nf = self.params['guard_ring_nf']

        # each segment contains two blocks, i.e. two parallel stack transistors
        num_blk = num_seg * 2

        row_list = ['nch', 'ptap', 'ntap', 'pch']
        w_list = [w_n, w_sub, w_sub, w_p]
        orient_list = ['R0', 'R0', 'MX', 'MX']
        thres_list = [threshold] * 4

        # compute number of tracks
        # note: because we're using thick wires, we need to compute space needed to
        # satisfy DRC rules
        vm_layer = self.conn_layer
        hm_layer = vm_layer + 1
        if sup_width > 1:
            nsp = max(sig_space, self.grid.get_num_space_tracks(hm_layer, sup_width, half_space=True, same_color=True))
        else:
            nsp = sig_space
        # to draw special stack driver primitive, we need to enable dual_gate options.
        options = dict(ds_low_res=True)
        row_kwargs = [options] * 4
        draw_boundaries = False
        end_mode = 0

        # find number of tracks iteratively
        num_g_tracks = [1, 0, 0, 1]
        num_gb_tracks = [1, 0, 0, 1]
        num_ds_tracks = [0, 0, 0, 0]

        # first iteration
        self.set_row_types(row_list, w_list, orient_list, thres_list, draw_boundaries, end_mode,
                           num_g_tracks, num_gb_tracks, num_ds_tracks, guard_ring_nf=guard_ring_nf,
                           row_kwargs=row_kwargs)

        # increase number of N gate tracks so we meet spacing rule between N input and N output
        ngidx = 0
        ndidx = self.get_track_index(0, 'gb', 0)
        cur_sp = ndidx - ngidx - 1
        if cur_sp < nsp:
            num_g_tracks = [1 + int(math.ceil(nsp - cur_sp)), 0, 0, 1]
            self.set_row_types(row_list, w_list, orient_list, thres_list, draw_boundaries, end_mode,
                               num_g_tracks, num_gb_tracks, num_ds_tracks, guard_ring_nf=guard_ring_nf,
                               row_kwargs=row_kwargs)
            ndidx = self.get_track_index(0, 'gb', 0)

        vss_idx = ndidx + (sup_width - 1) / 2
        ptap_didx = self.get_track_index(1, 'ds', 0)
        ntap_didx = self.get_track_index(2, 'ds', 0)
        mid_idx = (2 * (ptap_didx + ntap_didx) // 2) / 2
        out_idx = max(vss_idx + sup_width + nsp, mid_idx)
        vdd_idx = out_idx + (out_idx - vss_idx)
        vdd_edge_idx = vdd_idx + (sup_width - 1) / 2
        pdidx = self.get_track_index(3, 'gb', 0)

        # increase number of gate-bar tracks so we have sufficient room
        tot_gb_tracks = int(math.ceil(vdd_edge_idx - ndidx + 1))
        cur_gb_tracks = int(math.ceil(pdidx - ndidx + 1))
        inc_tracks = tot_gb_tracks - cur_gb_tracks
        if inc_tracks > 0:
            ninc = inc_tracks // 2
            pinc = inc_tracks - ninc
            num_gb_tracks = [num_gb_tracks[0] + ninc, 0, 0, num_gb_tracks[3] + pinc]
            self.set_row_types(row_list, w_list, orient_list, thres_list, draw_boundaries, end_mode,
                               num_g_tracks, num_gb_tracks, num_ds_tracks, guard_ring_nf=guard_ring_nf,
                               row_kwargs=row_kwargs)
            pdidx = self.get_track_index(3, 'gb', 0)

        # increase number of P gate tracks so we meet spacing rule between P input and P output
        pgidx = self.grid.coord_to_nearest_track(hm_layer, self.tot_height, mode=-2, unit_mode=True)
        cur_sp = pgidx - pdidx - 1
        if cur_sp < nsp:
            num_g_tracks = [num_g_tracks[0], 0, 0, 1 + int(math.ceil(nsp - cur_sp))]
            self.set_row_types(row_list, w_list, orient_list, thres_list, draw_boundaries, end_mode,
                               num_g_tracks, num_gb_tracks, num_ds_tracks, guard_ring_nf=guard_ring_nf,
                               row_kwargs=row_kwargs)
            pgidx = self.grid.coord_to_nearest_track(hm_layer, self.tot_height, mode=-2, unit_mode=True)

        # placement done

        # determine total number of blocks
        sub_space_blk = self.min_sub_space
        sub_blk = self.sub_columns
        tot_blk = num_blk + 2 * sub_blk + 2 * sub_space_blk

        # draw inner substrates
        # TODO: remove 1 block hard coding
        vss_gr = self._draw_gr(1, tot_blk)
        vdd_gr = self._draw_gr(2, tot_blk)

        # draw pmos row
        row_idx = 3
        p_dict, vdd_warrs = self._draw_core_row(row_idx, num_seg, sub_space_blk + sub_blk)

        # draw nmos row
        row_idx = 0
        n_dict, vss_warrs = self._draw_core_row(row_idx, num_seg, sub_space_blk + sub_blk)

        vdd_warrs.extend(vdd_gr)
        vss_warrs.extend(vss_gr)

        # compute overall block size
        self.set_laygo_size(num_col=tot_blk)
        self.fill_space()

        # fix length quantization rule for gate and source
        min_len = self.grid.get_min_length(vm_layer, 1)
        for gtype, ext_dir in (('g0', 0), ('g1', 0), ('s', 1)):
            for table, flip in ((n_dict, False), (p_dict, True)):
                warrs = table[gtype]
                if flip:
                    ext_dir = 1 - ext_dir
                if ext_dir == 0:
                    lower, upper = warrs[0].upper - min_len, warrs[0].upper
                else:
                    lower, upper = warrs[0].lower, warrs[0].lower + min_len

                self.extend_wires(warrs, lower=lower, upper=upper)

        # connect supplies
        vdd_warrs.extend(p_dict['s'])
        vss_warrs.extend(n_dict['s'])
        for name, warrs, row_idx, tr_idx in (('VDD', vdd_warrs, 1, vdd_idx), ('VSS', vss_warrs, 0, vss_idx)):
            tid = TrackID(hm_layer, tr_idx, width=sup_width)
            pin = self.connect_to_tracks(warrs, tid)
            self.add_pin(name, pin, show=show_pins)

        nbidx, niidx = ngidx, ngidx - 1
        pbidx, piidx = pgidx, pgidx + 1
        if parity == 1:
            nbidx, niidx = niidx, nbidx
            pbidx, piidx = piidx, pbidx

        # connect nmos/pmos gates
        for name, port, port_dict, tidx in (('nbias', 'g1', n_dict, nbidx), ('nin', 'g0', n_dict, niidx),
                                            ('pbias', 'g1', p_dict, pbidx), ('pin', 'g0', p_dict, piidx)):
            tid = TrackID(self.conn_layer + 1, tidx)
            pin = self.connect_to_tracks(port_dict[port], tid)
            self.add_pin(name, pin, show=show_pins)

        # connect output
        tid = TrackID(self.conn_layer + 1, out_idx, width=sup_width)
        pin = self.connect_to_tracks(p_dict['d'] + n_dict['d'], tid)
        self.add_pin('out', pin, show=show_pins)

    def _draw_gr(self, row_idx, tot_blk):
        # TODO: remove substrate block non-export location hard coding
        self.add_laygo_primitive('sub', loc=(0, row_idx), export=False)
        inst = self.add_laygo_primitive('sub', loc=(1, row_idx))
        warrs = inst.get_all_port_pins()
        self.add_laygo_primitive('sub', loc=(2, row_idx), nx=tot_blk - 4, spx=1, export=False)
        inst = self.add_laygo_primitive('sub', loc=(tot_blk-2, row_idx))
        warrs.extend(inst.get_all_port_pins())
        self.add_laygo_primitive('sub', loc=(tot_blk - 1, row_idx), export=False)
        return warrs

    def _draw_core_row(self, row_idx, num_seg, blk_offset):
        blk_type = 'stack2s'

        # add substrate at ends
        sub_inst = self.add_laygo_primitive('sub', loc=(0, row_idx))
        sup_warrs = sub_inst.get_all_port_pins()
        sub_inst = self.add_laygo_primitive('sub', loc=(2 * num_seg + 2 * blk_offset - self.sub_columns, row_idx))
        sup_warrs.extend(sub_inst.get_all_port_pins())

        # add core instances
        core_warrs = {'g0': [], 'g1': [], 'd': [], 's': []}
        for seg_idx in range(num_seg):
            for col_idx in (blk_offset + seg_idx * 2, blk_offset + seg_idx * 2 + 1):
                flip = (col_idx % 2) != (blk_offset % 2)
                inst = self.add_laygo_primitive(blk_type, loc=(col_idx, row_idx), flip=flip)
                for key, warrs in core_warrs.items():
                    warrs.extend(inst.get_all_port_pins(key))

        return core_warrs, sup_warrs


class StackDriverArray(DigitalBase):
    """A single diff amp.

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
        super(StackDriverArray, self).__init__(temp_db, lib_name, params, used_names, **kwargs)

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
            driver_params='stack driver parameters.',
            guard_ring_nf='number of guard ring fingers.',
            nx='number of columns.',
            ny='number of rows.',
            show_pins='True to draw pin geometries.',
        )

    def draw_layout(self):
        """Draw the layout of a dynamic latch chain.
        """
        drv0_params = self.params['driver_params'].copy()
        nx = self.params['nx']
        ny = self.params['ny']
        show_pins = self.params['show_pins']
        guard_ring_nf = self.params['guard_ring_nf']

        draw_boundaries = True
        end_mode = 15

        drv0_params['parity'] = 0
        drv0_params['guard_ring_nf'] = guard_ring_nf
        drv_master0 = self.new_template(params=drv0_params, temp_cls=StackDriver)
        drv1_params = drv0_params.copy()
        drv1_params['parity'] = 1
        drv_master1 = self.new_template(params=drv1_params, temp_cls=StackDriver)

        row_info = drv_master0.get_digital_row_info()

        self.initialize(row_info, ny, draw_boundaries, end_mode, guard_ring_nf=guard_ring_nf)

        spx = drv_master0.laygo_size[0]
        inst_list = []
        wire_table = {}
        for row_idx in range(ny):
            master = drv_master0 if row_idx % 2 == 0 else drv_master1
            cur_inst = self.add_digital_block(master, loc=(0, row_idx), nx=nx, spx=spx)
            inst_list.append(cur_inst)
            for name in ('VDD', 'VSS', 'pin', 'nin', 'pbias', 'nbias', 'out'):
                if name not in wire_table:
                    wire_table[name] = []
                wire_table[name].append(self.connect_wires(cur_inst.get_all_port_pins(name))[0])

        num_col = nx * spx
        sub_cols = self.laygo_info.sub_columns
        sub_port_cols = self.laygo_info.sub_port_columns
        port_unit = sub_port_cols + [spx - sub_cols + i for i in sub_port_cols]

        port_cols = list(port_unit)
        for idx in range(1, nx):
            port_cols.extend((i + idx * spx for i in port_unit))

        self.set_digital_size(num_col)
        bot_warrs, top_warrs, _, _ = self.fill_space(port_cols=port_cols)

        bot_hm = wire_table['VSS'][0]
        if ny % 2 == 0:
            top_hm = wire_table['VSS'][-1]
        else:
            top_hm = wire_table['VDD'][-1]

        self.connect_to_tracks(bot_warrs, bot_hm.track_id)
        self.connect_to_tracks(top_warrs, top_hm.track_id)

        # export ports
        for name, wires in wire_table.items():
            self.add_pin(name, wires, label=name + ':', show=show_pins)


def make_tdb(prj, target_lib, specs):
    grid_specs = specs['routing_grid']
    layers = grid_specs['layers']
    spaces = grid_specs['spaces']
    widths = grid_specs['widths']
    bot_dir = grid_specs['bot_dir']

    routing_grid = RoutingGrid(prj.tech_info, layers, spaces, widths, bot_dir)
    tdb = TemplateDB('template_libs.def', routing_grid, target_lib, use_cybagoa=True)
    return tdb


def generate_unit(prj):
    lib_name = 'AAAFOO'

    with open('specs_test/stack_driver_v3.yaml', 'r') as f:
        specs = yaml.load(f)

    params = specs['params']

    temp_db = make_tdb(prj, lib_name, specs)

    template = temp_db.new_template(params=params, temp_cls=StackDriver, debug=False)
    name = 'STACK_DRIVER_UNIT'
    print('create layout')
    temp_db.batch_layout(prj, [template], [name])
    print('done')


def generate_array(prj):
    lib_name = 'AAAFOO'

    with open('specs_test/stack_driver_array.yaml', 'r') as f:
        specs = yaml.load(f)

    params = specs['params']

    temp_db = make_tdb(prj, lib_name, specs)

    template = temp_db.new_template(params=params, temp_cls=StackDriverArray, debug=False)
    name = 'STACK_DRIVER_ARR'
    print('create layout')
    temp_db.batch_layout(prj, [template], [name])
    print('done')


if __name__ == '__main__':

    local_dict = locals()
    if 'bprj' not in local_dict:
        print('creating BAG project')
        bprj = BagProject()
    else:
        print('loading BAG project')
        bprj = local_dict['bprj']

    # generate_unit(bprj)
    generate_array(bprj)