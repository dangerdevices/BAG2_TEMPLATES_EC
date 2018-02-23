# -*- coding: utf-8 -*-

"""This module defines various substrate related classes."""

from typing import TYPE_CHECKING, Dict, Any, Set, Tuple, Optional

from bag.util.search import BinaryIterator
from bag.layout.template import TemplateBase, TemplateDB
from bag.layout.routing import TrackID
from bag.layout.util import BBox

from ..analog_mos.substrate import AnalogSubstrate
from ..analog_mos.edge import AnalogEdge, AnalogEndRow, SubRingEndRow
from ..analog_mos.mos import SubRingExt
from ..analog_mos.conn import AnalogSubstrateConn

from .base import AnalogBaseInfo

if TYPE_CHECKING:
    from ..analog_mos.core import MOSTech


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
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **kwargs) -> None
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._sub_bndx = None
        self._sub_bndy = None

    @property
    def port_name(self):
        return 'VDD' if self.params['sub_type'] == 'ntap' else 'VSS'

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
            tot_width_parity=None,
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
            top_layer='the top layer of the template.',
            lch='channel length, in meters.',
            w='substrate width, in meters/number of fins.',
            sub_type='substrate type.',
            threshold='substrate threshold flavor.',
            well_width='Width of the well in layout units.',
            show_pins='True to show pin labels.',
            is_passive='True if this substrate is used as substrate contact for passive devices.',
            tot_width_parity='width parity.  Used to guarantee templates will be centered.',
        )

    def get_substrate_box(self):
        # type: () -> Tuple[Optional[BBox], Optional[BBox]]
        """Returns the substrate tap bounding box."""
        (imp_yb, imp_yt), (thres_yb, thres_yt) = self._sub_bndy

        xl, xr = self._sub_bndx
        if xl is None or xr is None:
            return None, None

        res = self.grid.resolution
        if imp_yb is None or imp_yt is None:
            imp_box = None
        else:
            imp_box = BBox(xl, imp_yb, xr, imp_yt, res, unit_mode=True)
        if thres_yb is None or thres_yt is None:
            thres_box = None
        else:
            thres_box = BBox(xl, thres_yb, xr, thres_yt, res, unit_mode=True)

        return imp_box, thres_box

    def draw_layout(self):
        # type: () -> None

        top_layer = self.params['top_layer']
        lch = self.params['lch']
        w = self.params['w']
        sub_type = self.params['sub_type']
        threshold = self.params['threshold']
        well_width = self.params['well_width']
        show_pins = self.params['show_pins']
        is_passive = self.params['is_passive']
        tot_width_parity = self.params['tot_width_parity']

        sub_end_mode = 15
        res = self.grid.resolution
        well_width = int(round(well_width / res))

        # get layout info, also set RoutingGrid to substrate grid.
        layout_info = AnalogBaseInfo(self.grid, lch, 0, top_layer=top_layer, end_mode=sub_end_mode)
        # compute template width in number of sd pitches
        # find maximum number of fingers we can draw
        bin_iter = BinaryIterator(1, None)
        while bin_iter.has_next():
            cur_fg = bin_iter.get_next()
            cur_core_width = layout_info.get_core_width(cur_fg)
            if cur_core_width == well_width:
                bin_iter.save()
                break
            elif cur_core_width < well_width:
                bin_iter.save()
                bin_iter.up()
            else:
                bin_iter.down()

        sub_fg_tot = bin_iter.get_last_save()
        if sub_fg_tot is None:
            raise ValueError('Cannot draw substrate that fit in width: %d' % well_width)

        # check width parity requirement
        if tot_width_parity is not None:
            w_pitch = self.grid.get_size_pitch(top_layer, unit_mode=True)[0]
            place_info = layout_info.get_placement_info(sub_fg_tot)
            while sub_fg_tot > 0 and (place_info.tot_width // w_pitch) % 2 != tot_width_parity:
                sub_fg_tot -= 1
                place_info = layout_info.get_placement_info(sub_fg_tot)
            if sub_fg_tot <= 0:
                raise ValueError('Cannot draw substrate with width = %d, parity = %d' % (well_width, tot_width_parity))

        layout_info.set_fg_tot(sub_fg_tot)
        self.grid = layout_info.grid

        place_info = layout_info.get_placement_info(sub_fg_tot)
        edgel_x0 = place_info.edge_margins[0]
        arr_box_x = place_info.arr_box_x
        tot_width = place_info.tot_width

        # create substrate
        params = dict(
            lch=lch,
            w=w,
            sub_type=sub_type,
            threshold=threshold,
            fg=sub_fg_tot,
            top_layer=top_layer,
            options=dict(is_passive=is_passive),
        )
        sub_master = self.new_template(params=params, temp_cls=AnalogSubstrate)
        edge_layout_info = sub_master.get_edge_layout_info()
        edge_params = dict(
            is_end=True,
            guard_ring_nf=0,
            name_id=sub_master.get_layout_basename(),
            layout_info=edge_layout_info,
            adj_blk_info=sub_master.get_left_edge_info(),
        )
        edge_master = self.new_template(params=edge_params, temp_cls=AnalogEdge)

        end_row_params = dict(
            lch=lch,
            fg=sub_fg_tot,
            sub_type=sub_type,
            threshold=threshold,
            is_end=True,
            top_layer=top_layer,
        )
        end_row_master = self.new_template(params=end_row_params, temp_cls=AnalogEndRow)
        end_edge_params = dict(
            is_end=True,
            guard_ring_nf=0,
            name_id=end_row_master.get_layout_basename(),
            layout_info=end_row_master.get_edge_layout_info(),
            adj_blk_info=end_row_master.get_left_edge_info(),
        )
        end_edge_master = self.new_template(params=end_edge_params, temp_cls=AnalogEdge)
        conn_params = dict(
            layout_info=edge_layout_info,
            layout_name=sub_master.get_layout_basename() + '_subconn',
            is_laygo=False,
        )
        conn_master = self.new_template(params=conn_params, temp_cls=AnalogSubstrateConn)

        # find substrate height and set size
        hsub = sub_master.prim_bound_box.height_unit
        hend = end_row_master.prim_bound_box.height_unit
        htot = hsub + 2 * hend
        # add substrate and edge at the right locations
        x1 = edgel_x0 + edge_master.prim_bound_box.width_unit
        x2 = x1 + sub_master.prim_bound_box.width_unit + edge_master.prim_bound_box.width_unit
        y1 = end_edge_master.prim_bound_box.height_unit
        y2 = y1 + edge_master.prim_bound_box.height_unit + end_edge_master.prim_bound_box.height_unit
        instlb = self.add_instance(end_edge_master, inst_name='XLBE', loc=(edgel_x0, 0), unit_mode=True)
        self.add_instance(edge_master, inst_name='XLE', loc=(edgel_x0, y1), unit_mode=True)
        self.add_instance(end_edge_master, inst_name='XLTE', orient='MX', loc=(edgel_x0, y2), unit_mode=True)
        self.add_instance(end_row_master, inst_name='XB', loc=(x1, 0), unit_mode=True)
        self.add_instance(sub_master, inst_name='XSUB', loc=(x1, y1), unit_mode=True)
        self.add_instance(end_row_master, inst_name='XT', orient='MX', loc=(x1, y2), unit_mode=True)
        self.add_instance(end_edge_master, inst_name='XRBE', orient='MY', loc=(x2, 0), unit_mode=True)
        self.add_instance(edge_master, inst_name='XRE', orient='MY', loc=(x2, y1), unit_mode=True)
        sub_conn = self.add_instance(conn_master, inst_name='XSUBCONN', loc=(x1, y1), unit_mode=True)
        instrt = self.add_instance(end_edge_master, inst_name='XRTE', orient='R180', loc=(x2, y2), unit_mode=True)

        # calculate substrate Y coordinates
        imp_y, thres_y = end_row_master.sub_ysep
        self._sub_bndy = (imp_y, y2 - imp_y), (thres_y, y2 - thres_y)

        # get left/right substrate coordinates
        tot_imp_box = BBox.get_invalid_bbox()
        for lay in self.grid.tech_info.get_implant_layers('ptap'):
            tot_imp_box = tot_imp_box.merge(self.get_rect_bbox(lay))
        for lay in self.grid.tech_info.get_implant_layers('ntap'):
            tot_imp_box = tot_imp_box.merge(self.get_rect_bbox(lay))

        if not tot_imp_box.is_physical():
            self._sub_bndx = None, None
        else:
            self._sub_bndx = tot_imp_box.left_unit, tot_imp_box.right_unit

        # set array box and size
        arr_box = instlb.array_box.merge(instrt.array_box)
        self.array_box = BBox(arr_box_x[0], arr_box.bottom_unit, arr_box_x[1], arr_box.top_unit, res, unit_mode=True)
        self.set_size_from_bound_box(top_layer, BBox(0, 0, tot_width, htot, res, unit_mode=True))
        self.add_cell_boundary(self.bound_box)

        # find center track index
        hm_layer = layout_info.mconn_port_layer + 1
        hm_mid = self.grid.coord_to_nearest_track(hm_layer, self.array_box.yc_unit, mode=0,
                                                  half_track=True, unit_mode=True)
        # connect to horizontal metal layer.
        hm_pitch = self.grid.get_track_pitch(hm_layer, unit_mode=True)
        ntr = self.array_box.height_unit // hm_pitch  # type: int
        tr_width = self.grid.get_max_track_width(hm_layer, 1, ntr, half_end_space=False)
        track_id = TrackID(hm_layer, hm_mid, width=tr_width)
        port_name = 'VDD' if sub_type == 'ntap' else 'VSS'
        sub_wires = self.connect_to_tracks(sub_conn.get_port(port_name).get_pins(hm_layer - 1), track_id)
        self.add_pin(port_name, sub_wires, show=show_pins)


class SubstrateRing(TemplateBase):
    """A template that draws a ring of substrate taps around a given bounding box.

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
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **kwargs) -> None
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']  # type: MOSTech
        self._blk_loc = None

    @property
    def blk_loc_unit(self):
        return self._blk_loc

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        return dict(
            show_pins=False,
            dnw_mode='',
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
            top_layer='the top layer of the template.',
            bound_box='bounding box of the inner template',
            sub_type='the substrate type.',
            w='substrate tap width, in meters/number of fins.',
            fg_side='number of fingers in vertical substrate ring.',
            threshold='substrate threshold flavor.',
            show_pins='True to show pin labels.',
            dnw_mode='deep N-well mode string.  Empty string to disable.',
        )

    def draw_layout(self):
        # type: () -> None

        top_layer = self.params['top_layer']
        bound_box = self.params['bound_box']
        sub_type = self.params['sub_type']
        w = self.params['w']
        fg_side = self.params['fg_side']
        threshold = self.params['threshold']
        show_pins = self.params['show_pins']
        dnw_mode = self.params['dnw_mode']

        sub_end_mode = 15
        lch = self._tech_cls.get_substrate_ring_lch()

        # create layout masters
        box_w, box_h = bound_box.width_unit, bound_box.height_unit
        layout_info = AnalogBaseInfo(self.grid, lch, fg_side, top_layer=top_layer, end_mode=sub_end_mode,
                                     is_sub_ring=True, dnw_mode=dnw_mode)
        sd_pitch = layout_info.sd_pitch_unit
        mtop_lay = layout_info.mconn_port_layer + 1

        fg_tot = -(-box_w // sd_pitch)
        place_info = layout_info.get_placement_info(fg_tot)
        wtot = place_info.tot_width
        dx = place_info.edge_margins[0]
        arr_box_x = place_info.arr_box_x
        layout_info.set_fg_tot(fg_tot)
        self.grid = layout_info.grid

        if top_layer < mtop_lay:
            raise ValueError('top_layer = %d must be at least %d' % (top_layer, mtop_lay))

        htot, master_list, edge_list = self._make_masters(top_layer, mtop_lay, lch, fg_tot, w, fg_side,
                                                          sub_type, threshold, dnw_mode, box_h)

        # arrange layout masters
        # first, compute edge margins so everything is quantized properly.
        m_sub, m_end1, m_end2, m_ext = master_list
        e_sub, e_end1, e_end2, e_ext = edge_list
        e1_h = m_end1.bound_box.height_unit
        e2_h = m_end2.bound_box.height_unit
        sub_h = m_sub.bound_box.height_unit
        sub_w = m_sub.bound_box.width_unit
        e_sub_w = e_sub.bound_box.width_unit

        # add masters at correct locations
        m_list = [e_end1, m_end1, e_end1, e_sub, m_sub, e_sub, e_end2, m_end2, e_end2]
        xl_list = [dx, dx + e_sub_w, dx + e_sub_w + sub_w]
        yl_list = [0, e1_h, e1_h + sub_h]
        o_list = ['R0', 'R0', 'MY']
        self._blk_loc = ((wtot - box_w) // 2, (htot - box_h) // 2)

        # substrate connection master
        conn_params = dict(
            layout_info=m_sub.get_edge_layout_info(),
            layout_name=m_sub.get_layout_basename() + '_subconn',
            is_laygo=False,
        )
        m_conn = self.new_template(params=conn_params, temp_cls=AnalogSubstrateConn)

        # add substrate row masters
        edge_inst_list = []
        conn_list = []
        tid_list = []
        hm_pitch = self.grid.get_track_pitch(mtop_lay, unit_mode=True)
        for name_fmt, flip_ud, yoff in (('XB%d', False, 0), ('XT%d', True, htot)):
            m_idx = 0
            for yidx, yl in enumerate(yl_list):
                for xidx, (xl, orient) in enumerate(zip(xl_list, o_list)):
                    master = m_list[m_idx]
                    cur_name = name_fmt % m_idx  # type: str
                    if not master.is_empty:
                        if flip_ud:
                            orient = 'MX' if orient == 'R0' else 'R180'
                        if orient == 'R0':
                            loc = (xl, yl)
                        elif orient == 'MY':
                            loc = (xl + master.bound_box.width_unit, yl)
                        elif orient == 'MX':
                            loc = (xl, yoff - yl)
                        elif orient == 'R180':
                            loc = (xl + master.bound_box.width_unit, yoff - yl)
                        inst = self.add_instance(master, inst_name=cur_name, loc=loc, orient=orient, unit_mode=True)
                        if xidx == 0 or xidx == 2:
                            edge_inst_list.append(inst)
                        elif xidx == 1 and yidx == 1:
                            # get supply TrackID
                            hm_tidx = self.grid.coord_to_track(mtop_lay, inst.bound_box.yc_unit, unit_mode=True)
                            ntr = inst.bound_box.height_unit // hm_pitch  # type: int
                            tr_width = self.grid.get_max_track_width(mtop_lay, 1, ntr, half_end_space=False)
                            tid_list.append(TrackID(mtop_lay, hm_tidx, width=tr_width))
                            inst = self.add_instance(m_conn, inst_name=cur_name + '_CONN', loc=loc,
                                                     orient=orient, unit_mode=True)
                            conn_list.append(inst)
                    m_idx += 1

        # add left and right edge
        hsub = e1_h + e2_h + sub_h
        edge_inst_list.append(self.add_instance(e_ext, inst_name='XEL', loc=(dx, hsub), unit_mode=True))
        edge_inst_list.append(self.add_instance(e_ext, inst_name='XER', loc=(wtot - dx, hsub),
                                                orient='MY', unit_mode=True))

        # set size and array box
        res = self.grid.resolution
        bnd_box = BBox(0, 0, wtot, htot, res, unit_mode=True)
        if top_layer > mtop_lay:
            self.set_size_from_bound_box(top_layer, bnd_box)
        else:
            self.prim_top_layer = top_layer
            self.prim_bound_box = bnd_box
        self.array_box = BBox(arr_box_x[0], 0, arr_box_x[1], htot, res, unit_mode=True)
        self.add_cell_boundary(self.bound_box)

        if dnw_mode:
            # add overlay DNW layer
            for lay in self.grid.tech_info.get_dnw_layers():
                dnw_box = self.get_rect_bbox(lay)
                self.add_rect(lay, dnw_box)

        # connect to horizontal metal layer.
        port_name = 'VDD' if sub_type == 'ntap' else 'VSS'
        conn_warr_list, dum_warr_list = [], []
        dum_layer = self._tech_cls.get_dum_conn_layer()
        for inst in edge_inst_list:
            if inst.has_port(port_name):
                conn_warr_list.extend(inst.get_all_port_pins(port_name, layer=mtop_lay - 1))
                dum_warr_list.extend(inst.get_all_port_pins(port_name, layer=dum_layer))

        self.connect_wires(dum_warr_list)
        edge_warrs = self.connect_wires(conn_warr_list)

        for conn_inst, tid in zip(conn_list, tid_list):
            cur_warrs = edge_warrs + conn_inst.get_port(port_name).get_pins(mtop_lay - 1)
            sub_wires = self.connect_to_tracks(cur_warrs, tid)
            self.add_pin(port_name, sub_wires, show=show_pins)

    def _make_masters(self, top_layer, mtop_lay, lch, fg_tot, w, fg_side, sub_type, threshold, dnw_mode, box_h):
        options1 = dict(is_sub_ring=True, dnw_mode=dnw_mode)
        options2 = dict(dnw_mode=dnw_mode)
        options3 = options1.copy()
        options3['integ_htr'] = True

        sub_params = dict(
            lch=lch,
            fg=fg_tot,
            w=w,
            sub_type=sub_type,
            threshold=threshold,
            top_layer=mtop_lay,
            options=options3,
        )
        sub_master = self.new_template(params=sub_params, temp_cls=AnalogSubstrate)

        end1_params = dict(
            lch=lch,
            fg=fg_tot,
            sub_type=sub_type,
            threshold=threshold,
            is_end=True,
            top_layer=mtop_lay,
            options=options1,
        )
        end1_master = self.new_template(params=end1_params, temp_cls=AnalogEndRow)

        end2_params = dict(
            fg=fg_tot,
            sub_type=sub_type,
            threshold=threshold,
            end_ext_info=sub_master.get_ext_top_info(),
            options=options2,
        )
        end2_master = self.new_template(params=end2_params, temp_cls=SubRingEndRow)

        # compute extension height
        hsub = sub_master.bound_box.height_unit + end1_master.bound_box.height_unit + end2_master.bound_box.height_unit
        hmin = 2 * hsub + box_h
        blk_h = self.grid.get_block_size(top_layer, unit_mode=True)[1]
        if box_h % blk_h != 0:
            raise ValueError('Template height = %d is not multiples of %d' % (box_h, blk_h))

        htot = -(-hmin // blk_h) * blk_h
        if ((htot - box_h) // blk_h) % 2 == 1:
            # make sure template has integer number of blocks from top and bottom.
            htot += blk_h

        ext_params = dict(
            sub_type=sub_type,
            height=htot - 2 * hsub,
            fg=fg_tot,
            end_ext_info=end2_master.get_ext_info(),
            options=options2,
        )
        ext_master = self.new_template(params=ext_params, temp_cls=SubRingExt)

        master_list = [sub_master, end1_master, end2_master, ext_master]

        edge_list = []
        for master in master_list:
            edge_params = dict(
                is_end=True,
                guard_ring_nf=fg_side,
                name_id=master.get_layout_basename(),
                layout_info=master.get_edge_layout_info(),
                adj_blk_info=master.get_left_edge_info(),
            )
            edge_list.append(self.new_template(params=edge_params, temp_cls=AnalogEdge))

        return htot, master_list, edge_list


class DeepNWellRing(TemplateBase):
    """A template that draws a deep N-well double ring around a template.

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
        super(DeepNWellRing, self).__init__(temp_db, lib_name, params, used_names, **kwargs)
        self._tech_cls = self.grid.tech_info.tech_params['layout']['mos_tech_class']  # type: MOSTech
        self._blk_loc = None

    @property
    def blk_loc_unit(self):
        return self._blk_loc

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        return dict(
            show_pins=False,
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
            top_layer='the top layer of the template.',
            bound_box='bounding box of the inner template',
            w='substrate tap width, in meters/number of fins.',
            fg_side='number of fingers in vertical substrate ring.',
            threshold='substrate threshold flavor.',
            show_pins='True to show pin labels.',
            dnw_mode='deep N-well mode string.  This determines the DNW spacing to adjacent blocks.',
        )

    def draw_layout(self):
        # type: () -> None

        top_layer = self.params['top_layer']
        bound_box = self.params['bound_box']
        w = self.params['w']
        fg_side = self.params['fg_side']
        threshold = self.params['threshold']
        show_pins = self.params['show_pins']
        dnw_mode = self.params['dnw_mode']

        # test top_layer
        hm_layer = self._tech_cls.get_mos_conn_layer() + 1
        if top_layer <= hm_layer:
            raise ValueError('top layer for DeepNWellRing must be >= %d' % (hm_layer + 1))

        # make masters
        dnw_params = dict(
            top_layer=top_layer,
            bound_box=bound_box,
            sub_type='ntap',
            w=w,
            fg_side=fg_side,
            threshold=threshold,
            show_pins=False,
            dnw_mode='compact',
        )
        dnw_master = self.new_template(params=dnw_params, temp_cls=SubstrateRing)
        dnw_blk_loc = dnw_master.blk_loc_unit

        sub_params = dict(
            top_layer=top_layer,
            bound_box=dnw_master.bound_box,
            sub_type='ptap',
            w=w,
            fg_side=fg_side,
            threshold=threshold,
            show_pins=False,
        )
        sub_master = self.new_template(params=sub_params, temp_cls=SubstrateRing)
        sub_blk_loc = sub_master.blk_loc_unit

        # put masters at (0, 0)
        sub_inst = self.add_instance(sub_master, 'XSUB')
        dnw_inst = self.add_instance(dnw_master, 'XDNW', loc=sub_blk_loc, unit_mode=True)

        # check how much to move substrate rings by to achive the DNW margin.
        x_pitch, y_pitch = self.grid.get_block_size(top_layer, unit_mode=True)
        dnw_margin = self.grid.tech_info.get_dnw_margin_unit(dnw_mode)
        dnw_box = BBox.get_invalid_bbox()
        for dnw_lay in self.grid.tech_info.get_dnw_layers():
            dnw_box = dnw_box.merge(dnw_inst.get_rect_bbox(dnw_lay))

        dx = -(-max(0, dnw_margin - dnw_box.left_unit) // x_pitch) * x_pitch
        dy = -(-max(0, dnw_margin - dnw_box.bottom_unit) // x_pitch) * x_pitch
        self.move_all_by(dx=dx, dy=dy, unit_mode=True)

        # set size
        res = self.grid.resolution
        sub_w = sub_master.bound_box.width_unit
        sub_h = sub_master.bound_box.height_unit
        bnd_box = BBox(0, 0, sub_w + 2 * dx, sub_h + 2 * dy, res, unit_mode=True)
        self.set_size_from_bound_box(top_layer, bnd_box)
        self.array_box = bnd_box
        self.add_cell_boundary(bnd_box)

        # record block location
        dnw_loc = dnw_inst.location_unit
        self._blk_loc = dnw_loc[0] + dnw_blk_loc[0], dnw_loc[1] + dnw_blk_loc[1]

        # export supplies
        self.reexport(sub_inst.get_port('VSS'), show=show_pins)
        self.reexport(dnw_inst.get_port('VDD'), show=show_pins)
