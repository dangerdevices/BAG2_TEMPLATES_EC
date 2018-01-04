# -*- coding: utf-8 -*-

from typing import Dict, Any, Set

from bag import float_to_si_string
from bag.math import lcm
from bag.layout.template import TemplateBase, TemplateDB

from .core import MOSTech


class AnalogSubstrateCore(TemplateBase):
    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        super(AnalogSubstrateCore, self).__init__(temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']  # type: MOSTech
        self.prim_top_layer = self._tech_cls.get_mos_conn_layer()

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
            layout_name='name of the layout cell.',
            layout_info='the layout information dictionary.',
        )

    def get_layout_basename(self):
        return self.params['layout_name']

    def compute_unique_key(self):
        return self.to_immutable_id((self.params['layout_name'], self.params['layout_info']))

    def draw_layout(self):
        layout_info = self.params['layout_info']

        # draw substrate
        self._tech_cls.draw_mos(self, layout_info)


class AnalogSubstrate(TemplateBase):
    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        super(AnalogSubstrate, self).__init__(temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']  # type: MOSTech
        self.prim_top_layer = self._tech_cls.get_mos_conn_layer()
        self._layout_info = None
        self._ext_top_info = None
        self._ext_bot_info = None
        self._left_edge_info = None
        self._right_edge_info = None
        self._sd_yc = None

    def get_ext_top_info(self):
        return self._ext_top_info

    def get_ext_bot_info(self):
        return self._ext_bot_info

    def get_left_edge_info(self):
        return self._left_edge_info

    def get_right_edge_info(self):
        return self._right_edge_info

    def get_sd_yc(self):
        return self._sd_yc

    def get_edge_layout_info(self):
        return self._layout_info

    @classmethod
    def get_default_param_values(cls):
        return dict(
            options={},
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
            lch='channel length, in meters.',
            w='transistor width, in meters/number of fins.',
            sub_type="substrate type, either 'ptap' or 'ntap'.",
            threshold='transistor threshold flavor.',
            fg='number of substrate fingers.',
            top_layer='The top routing layer.  Used to determine vertical pitch.',
            options='Optional layout parameters.',
        )

    def get_layout_basename(self):
        fmt = '%s_l%s_w%s_%s_lay%d_fg%d'
        sub_type = self.params['sub_type']
        lstr = float_to_si_string(self.params['lch'])
        wstr = float_to_si_string(self.params['w'])
        fg = self.params['fg']
        th = self.params['threshold']
        top_layer = self.params['top_layer']

        if top_layer is None:
            top_layer = 0
        basename = fmt % (sub_type, lstr, wstr, th, top_layer, fg)

        return basename

    def compute_unique_key(self):
        key = self.get_layout_basename(), self.params['options']
        return self.to_immutable_id(key)

    def draw_layout(self):
        lch = self.params['lch']
        w = self.params['w']
        fg = self.params['fg']
        sub_type = self.params['sub_type']
        threshold = self.params['threshold']
        top_layer = self.params['top_layer']
        options = self.params['options']

        integ_htr = options.get('integ_htr', False)

        res = self.grid.resolution
        lch_unit = int(round(lch / self.grid.layout_unit / res))

        if top_layer is not None:
            blk_pitch = self.grid.get_block_size(top_layer, unit_mode=True)[1]
            if integ_htr:
                hm_layer = top_layer
                while self.grid.get_direction(hm_layer) != 'x':
                    hm_layer -= 1
                blk_pitch = lcm([blk_pitch, self.grid.get_track_pitch(hm_layer, unit_mode=True)])
        else:
            blk_pitch = 1
        info = self._tech_cls.get_substrate_info(lch_unit, w, sub_type, threshold, fg, blk_pitch=blk_pitch, **options)
        self._layout_info = info['layout_info']
        self._sd_yc = info['sd_yc']
        self._ext_top_info = info['ext_top_info']
        self._ext_bot_info = info['ext_bot_info']
        self._left_edge_info = info['left_edge_info']
        self._right_edge_info = info['right_edge_info']

        core_params = dict(
            layout_name=self.get_layout_basename() + '_core',
            layout_info=self._layout_info,
        )

        master = self.new_template(params=core_params, temp_cls=AnalogSubstrateCore)
        inst = self.add_instance(master, 'XCORE')
        self.array_box = master.array_box
        self.prim_bound_box = master.prim_bound_box

        for port_name in inst.port_names_iter():
            self.reexport(inst.get_port(port_name), show=False)
