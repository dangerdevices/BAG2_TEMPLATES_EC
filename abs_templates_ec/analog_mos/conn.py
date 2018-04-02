# -*- coding: utf-8 -*-

"""This module defines abstract analog mosfet template classes.
"""

from typing import Dict, Any, Set

from bag import float_to_si_string
from bag.layout.template import TemplateBase, TemplateDB


class AnalogMOSConn(TemplateBase):
    """The abstract base class for finfet layout classes.

    This class provides the draw_foundation() method, which draws the poly array
    and implantation layers.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']
        self.prim_top_layer = self._tech_cls.get_mos_conn_layer()

    @classmethod
    def get_default_param_values(cls):
        return dict(
            min_ds_cap=False,
            gate_pref_loc='d',
            is_diff=False,
            diode_conn=False,
            gate_ext_mode=0,
            options=None,
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
            fg='number of fingers.',
            sdir='source connection direction.  0 for down, 1 for middle, 2 for up.',
            ddir='drain connection direction.  0 for down, 1 for middle, 2 for up.',
            min_ds_cap='True to minimize parasitic Cds.',
            gate_pref_loc="Preferred gate vertical track location.  Either 's' or 'd'.",
            is_diff='True to draw a differential pair connection instead (shared source).',
            diode_conn='True to short drain/gate',
            gate_ext_mode='connect gate using lower level metal to adjacent transistors.',
            options='Dictionary of transistor row options.',
        )

    def get_layout_basename(self):
        """Returns the base name for this template.

        Returns
        -------
        base_name : str
            the base name of this template.
        """

        lch_str = float_to_si_string(self.params['lch'])
        w_str = float_to_si_string(self.params['w'])
        prefix = 'mconn'
        if self.params['is_diff']:
            prefix += '_diff'

        basename = '%s_l%s_w%s_fg%d_s%d_d%d_g%s' % (prefix, lch_str, w_str,
                                                    self.params['fg'],
                                                    self.params['sdir'],
                                                    self.params['ddir'],
                                                    self.params['gate_pref_loc'],
                                                    )

        if self.params['min_ds_cap']:
            basename += '_minds'
        if self.params['diode_conn']:
            basename += '_diode'
        gext = self.params['gate_ext_mode']
        if gext > 0:
            basename += '_gext%d' % gext
        return basename

    def compute_unique_key(self):
        basename = self.get_layout_basename()
        return self.to_immutable_id((basename, self.grid.get_flip_parity(), self.params['options']))

    def draw_layout(self):
        lch = self.params['lch']
        w = self.params['w']
        fg = self.params['fg']
        sdir = self.params['sdir']
        ddir = self.params['ddir']
        gate_pref_loc = self.params['gate_pref_loc']
        gate_ext_mode = self.params['gate_ext_mode']
        min_ds_cap = self.params['min_ds_cap']
        is_diff = self.params['is_diff']
        diode_conn = self.params['diode_conn']
        options = self.params['options']

        if options is None:
            options = {}

        res = self.grid.resolution
        lch_unit = int(round(lch / self.grid.layout_unit / res))
        mos_info = self._tech_cls.get_mos_info(lch_unit, w, 'nch', 'standard', fg)
        self._tech_cls.draw_mos_connection(self, mos_info, sdir, ddir, gate_pref_loc, gate_ext_mode,
                                           min_ds_cap, is_diff, diode_conn, options)


class AnalogMOSDummy(TemplateBase):
    """An abstract template for analog mosfet dummy.

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
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']
        self.prim_top_layer = self._tech_cls.get_dum_conn_layer()

    @classmethod
    def get_default_param_values(cls):
        return dict(options=None)

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
            fg='number of fingers.',
            edge_mode='Whether to connect to source/drain on left/right edges.',
            gate_tracks='list of track numbers to draw dummy gate connections.',
            options='Dictionary of transistor row options.',
        )

    def get_layout_basename(self):
        """Returns the base name for this template.

        Returns
        -------
        base_name : str
            the base name of this template.
        """

        lch_str = float_to_si_string(self.params['lch'])
        w_str = float_to_si_string(self.params['w'])
        fg = self.params['fg']
        edge_mode = self.params['edge_mode']

        basename = 'mdum_l%s_w%s_fg%d_edge%d' % (lch_str, w_str, fg, edge_mode)

        return basename

    def compute_unique_key(self):
        basename = self.get_layout_basename()
        gtr = tuple(int(2 * v) for v in self.params['gate_tracks'])
        return self.to_immutable_id((basename, gtr, self.grid.get_flip_parity()))

    def draw_layout(self):
        lch = self.params['lch']
        w = self.params['w']
        fg = self.params['fg']
        edge_mode = self.params['edge_mode']
        gate_tracks = self.params['gate_tracks']
        options = self.params['options']

        if options is None:
            options = {}

        res = self.grid.resolution
        lch_unit = int(round(lch / self.grid.layout_unit / res))
        mos_info = self._tech_cls.get_mos_info(lch_unit, w, 'nch', 'standard', fg)
        self._tech_cls.draw_dum_connection(self, mos_info, edge_mode, gate_tracks, options)


class AnalogMOSDecap(TemplateBase):
    """An abstract template for analog mosfet dummy.

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
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']
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
            lch='channel length, in meters.',
            w='transistor width, in meters/number of fins.',
            fg='number of fingers.',
            sdir='source connection direction.',
            ddir='drain connection direction.',
            gate_ext_mode='connect gate using lower level metal to adjacent transistors.',
            export_gate='True to export gate to higher level metal.',
            options='Dictionary of transistor row options.',
        )

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
            gate_ext_mode=0,
            export_gate=False,
            sdir=1,
            ddir=1,
            options=None,
        )

    def get_layout_basename(self):
        """Returns the base name for this template.

        Returns
        -------
        base_name : str
            the base name of this template.
        """

        lch_str = float_to_si_string(self.params['lch'])
        w_str = float_to_si_string(self.params['w'])
        gext = self.params['gate_ext_mode']
        basename = 'mdecap_l%s_w%s_fg%d_gext%d_s%d_d%d' % (lch_str, w_str, self.params['fg'], gext,
                                                           self.params['sdir'], self.params['ddir'])
        if self.params['export_gate']:
            basename += '_gport'
        return basename

    def compute_unique_key(self):
        return self.to_immutable_id((self.get_layout_basename(), self.grid.get_flip_parity()))

    def draw_layout(self):
        lch = self.params['lch']
        w = self.params['w']
        fg = self.params['fg']
        sdir = self.params['sdir']
        ddir = self.params['ddir']
        gate_ext_mode = self.params['gate_ext_mode']
        export_gate = self.params['export_gate']
        options = self.params['options']

        if options is None:
            options = {}

        res = self.grid.resolution
        lch_unit = int(round(lch / self.grid.layout_unit / res))
        mos_info = self._tech_cls.get_mos_info(lch_unit, w, 'nch', 'standard', fg)
        self._tech_cls.draw_decap_connection(self, mos_info, sdir, ddir, gate_ext_mode,
                                             export_gate, options)


class AnalogSubstrateConn(TemplateBase):
    """The abstract base class for finfet layout classes.

    This class provides the draw_foundation() method, which draws the poly array
    and implantation layers.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **Any) -> None
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']
        self.prim_top_layer = self._tech_cls.get_mos_conn_layer()
        self.has_connection = False

    @classmethod
    def get_default_param_values(cls):
        return dict(
            dummy_only=False,
            port_tracks=[],
            dum_tracks=[],
            exc_tracks=[],
            is_laygo=False,
            is_guardring=False,
            options=None,
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
            layout_name='name of the layout cell.',
            layout_info='the layout information dictionary.',
            dummy_only='True if only dummy connections will be made to this substrate.',
            port_tracks='Substrate port must contain these track indices.',
            dum_tracks='Dummy port must contain these track indices.',
            exc_tracks='Do not draw tracks on these indices.',
            is_laygo='True if this is laygo substrate connection.',
            is_guardring='True if this is guardring substrate connection.',
            options='Additional substrate connection options.'
        )

    def get_layout_basename(self):
        return self.params['layout_name']

    def compute_unique_key(self):
        basename = self.get_layout_basename()
        layout_info = self.params['layout_info']
        dummy_only = self.params['dummy_only']
        port_tracks = tuple(int(2 * v) for v in self.params['port_tracks'])
        dum_tracks = tuple(int(2 * v) for v in self.params['dum_tracks'])
        exc_tracks = tuple(int(2 * v) for v in self.params['exc_tracks'])
        is_laygo = self.params['is_laygo']
        is_guardring = self.params['is_guardring']
        flip_parity = self.grid.get_flip_parity()
        options = self.params['options']
        return self.to_immutable_id((basename, port_tracks, dum_tracks, exc_tracks, layout_info,
                                     flip_parity, is_laygo, is_guardring, dummy_only, options))

    def draw_layout(self):
        layout_info = self.params['layout_info']
        dummy_only = self.params['dummy_only']
        port_tracks = self.params['port_tracks']
        dum_tracks = self.params['dum_tracks']
        exc_tracks = self.params['exc_tracks']
        is_laygo = self.params['is_laygo']
        is_guardring = self.params['is_guardring']
        options = self.params['options']

        if options is None:
            options = {}

        tmp = self._tech_cls.draw_substrate_connection(self, layout_info, port_tracks, dum_tracks,
                                                       exc_tracks, dummy_only, is_laygo,
                                                       is_guardring, options)
        self.has_connection = tmp
