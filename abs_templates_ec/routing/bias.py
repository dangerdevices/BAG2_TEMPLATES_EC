# -*- coding: utf-8 -*-

"""This module defines bias routing related templates."""

from typing import TYPE_CHECKING, Dict, Set, Any, Iterable, List, Union, Tuple, Generator, Optional

from collections import namedtuple
from itertools import chain, repeat, islice

from bag.math import lcm
from bag.util.interval import IntervalSet
from bag.layout.util import BBox
from bag.layout.template import TemplateBase
from bag.layout.routing.base import TrackManager, TrackID, WireArray

if TYPE_CHECKING:
    from bag.layout.routing.grid import RoutingGrid
    from bag.layout.template import TemplateDB

BiasInfo = namedtuple('BiasInfo', ['tracks', 'supplies', 'p0', 'p1'])


class BiasShield(TemplateBase):
    """Unit cell template for shield around bias wires.

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
    **kwargs :
        dictionary of optional parameters.  See documentation of
        :class:`bag.layout.template.TemplateBase` for details.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **kwargs) -> None
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._route_tids = None
        self._sup_intv = None

    @property
    def route_tids(self):
        return self._route_tids

    @property
    def sup_intv(self):
        return self._sup_intv

    @classmethod
    def get_params_info(cls):
        # type: () -> Dict[str, str]
        return dict(
            layer='the routing layer.',
            nwire='number of routing wires.',
            bias_config='The bias configuration dictionary.',
            top='True to draw top shield.',
            width='route wire width.',
            space_sig='route wire spacing.',
        )

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        return dict(
            top=True,
            width=1,
            space_sig=0,
        )

    def get_layout_basename(self):
        layer = self.params['layer']
        nwire = self.params['nwire']
        desc = 'top' if self.params['top'] else 'bot'
        return 'bias_shield_%s_lay%d_n%d' % (desc, layer, nwire)

    def draw_layout(self):
        # type: () -> None
        route_layer = self.params['layer']
        bias_config = self.params['bias_config']
        nwire = self.params['nwire']
        width = self.params['width']
        space_sig = self.params['space_sig']
        top = self.params['top']

        grid = self.grid
        res = grid.resolution

        bot_layer = route_layer - 1
        top_layer = route_layer + 1
        bot_pitch = grid.get_track_pitch(bot_layer, unit_mode=True)
        route_dir = grid.get_direction(route_layer)
        is_horiz = (route_dir == 'x')

        # compute size
        tot_w, tot_h = self.get_block_size(grid, route_layer, bias_config, nwire,
                                           width=width, space_sig=space_sig)
        if is_horiz:
            dim_perp = tot_h
            dim_par = tot_w
        else:
            dim_perp = tot_w
            dim_par = tot_h
        bbox = BBox(0, 0, tot_w, tot_h, res, unit_mode=True)
        self.prim_top_layer = top_layer
        self.prim_bound_box = bbox
        self.array_box = bbox

        # compute wire location
        tr_manager = TrackManager(grid, {'sig': {route_layer: width}},
                                  {('sig', ''): {route_layer: space_sig}}, half_space=True)
        route_w = bias_config[route_layer][1]
        tmp = [route_w]
        route_list = list(chain(tmp, repeat('sig', nwire), tmp))
        route_pitch = grid.get_track_pitch(route_layer, unit_mode=True)
        route_ntr = dim_perp / route_pitch
        locs = tr_manager.align_wires(route_layer, route_list, route_ntr, alignment=0, start_idx=0)

        self._route_tids = list(chain([(locs[0], route_w)],
                                      ((locs[idx], width) for idx in range(1, nwire + 1)),
                                      [(locs[nwire + 1], route_w)]))

        pitch = locs[nwire + 1] - locs[0]
        tr_upper = bbox.width_unit if is_horiz else bbox.height_unit
        sh_warr = self.add_wires(route_layer, locs[0], 0, tr_upper, num=2, pitch=pitch,
                                 unit_mode=True)

        sup_layer = top_layer if top else bot_layer
        pitch2 = grid.get_track_pitch(sup_layer, unit_mode=True) // 2
        sup_np2, sup_w, sup_spe2, sup_p2 = bias_config[sup_layer]
        sup_unit = sup_np2 * pitch2
        num = dim_par // sup_unit
        if num == 1:
            num = 1 if sup_p2 == 0 else 1 + (sup_np2 - 2 * sup_spe2) // sup_p2
            sup_tid = TrackID(sup_layer, sup_spe2 / 2, num=num, pitch=sup_p2 / 2)
            warr = self.connect_to_tracks(sh_warr, sup_tid)
        else:
            if sup_p2 == 0:
                sup_tid = TrackID(sup_layer, sup_spe2 / 2, num=num, pitch=sup_np2 / 2)
                warr = self.connect_to_tracks(sh_warr, sup_tid)
            else:
                # TODO: come back to fix this
                raise ValueError('umm...see Eric')

        self.add_pin('sup', warr, show=False)
        sup_box = warr.get_bbox_array(self.grid).get_overall_bbox()
        self._sup_intv = sup_box.get_interval(route_dir, unit_mode=True)

    @classmethod
    def get_block_size(cls, grid, route_layer, bias_config, nwire, width=1, space_sig=0):
        # type: (RoutingGrid, int, Dict[int, Tuple[int, ...]], int, int, int) -> Tuple[int, int]

        bot_layer = route_layer - 1
        top_layer = route_layer + 1
        route_dir = grid.get_direction(route_layer)
        is_horiz = route_dir == 'x'

        # calculate dimension
        bot_pitch2 = grid.get_track_pitch(bot_layer, unit_mode=True) // 2
        route_pitch2 = grid.get_track_pitch(route_layer, unit_mode=True) // 2
        top_pitch2 = grid.get_track_pitch(top_layer, unit_mode=True) // 2
        bot_np2, bot_w, bot_spe2, _ = bias_config[bot_layer]
        route_np2, route_w, route_spe2, _ = bias_config[route_layer]
        top_np2, top_w, top_spe2, _ = bias_config[top_layer]
        bot_unit = bot_np2 * bot_pitch2
        route_unit = route_np2 * route_pitch2
        top_unit = top_np2 * top_pitch2
        dim_par = lcm([bot_unit, top_unit])

        tr_manager = TrackManager(grid, {'sig': {route_layer: width}},
                                  {('sig', ''): {route_layer: space_sig}}, half_space=True)

        tmp = [route_w]
        route_list = list(chain(tmp, repeat('sig', nwire), tmp))
        _, locs = tr_manager.place_wires(route_layer, route_list)
        num_htr = int(2 * (locs[nwire + 1] - locs[0])) + 2 * route_spe2
        dim_perp = -(-(num_htr * route_pitch2) // route_unit) * route_unit
        if is_horiz:
            return dim_par, dim_perp
        else:
            return dim_perp, dim_par

    @classmethod
    def draw_bias_shields(cls,  # type: BiasShield
                          template,  # type: TemplateBase
                          layer,  # type: int
                          bias_config,  # type: Dict[int, Tuple[int, ...]]
                          warr_list2,  # type: List[Union[WireArray, Iterable[WireArray]]]
                          offset,  # type: int
                          width=1,  # type: int
                          space_sig=0,  # type: int
                          tr_lower=None,  # type: Optional[int]
                          tr_upper=None,  # type: Optional[int]
                          lu_end_mode=0,  # type: int
                          ):
        # type: (...) -> BiasInfo
        grid = template.grid

        nwire = len(warr_list2)
        params = dict(
            layer=layer,
            nwire=nwire,
            bias_config=bias_config,
            top=False,
            width=width,
            space_sig=space_sig,
        )
        bot_master = template.new_template(params=params, temp_cls=BiasShield)
        sh_box = bot_master.bound_box
        params['top'] = True
        top_master = template.new_template(params=params, temp_cls=BiasShield)

        route_tids = bot_master.route_tids
        tr_dir = grid.get_direction(layer)
        is_horiz = tr_dir == 'x'
        qdim = sh_box.width_unit if is_horiz else sh_box.height_unit
        tr0 = grid.coord_to_track(layer, offset, unit_mode=True) + 0.5
        bot_warrs = []
        top_warrs = []
        bot_intvs = IntervalSet()
        top_intvs = IntervalSet()
        if lu_end_mode == 0:
            min_len_mode = 0
        elif lu_end_mode & 2 != 0:
            min_len_mode = 1
        else:
            min_len_mode = -1
        tr_warr_list = []
        for warr_list, (tidx, tr_width) in zip(warr_list2, islice(route_tids, 1, nwire + 1)):
            if isinstance(warr_list, WireArray):
                warr_list = [warr_list]

            cur_tid = TrackID(layer, tidx + tr0, width=width)
            tr_warr = template.connect_to_tracks(warr_list, cur_tid, min_len_mode=min_len_mode)
            tr_warr_list.append(tr_warr)
            if tr_warr is not None:
                if tr_lower is None:
                    tr_lower = tr_warr.lower_unit
                else:
                    tr_lower = min(tr_lower, tr_warr.lower_unit)
                if tr_upper is None:
                    tr_upper = tr_warr.upper_unit
                else:
                    tr_upper = max(tr_upper, tr_warr.upper_unit)

            for warr in warr_list:
                cur_layer = warr.layer_id
                if cur_layer == layer - 1:
                    bot_warrs.append(warr)
                    cur_intvs = bot_intvs
                elif cur_layer == layer + 1:
                    top_warrs.append(warr)
                    cur_intvs = top_intvs
                else:
                    raise ValueError('Cannot connect to wire %s' % warr)

                cur_width = warr.width
                sp = grid.get_space(cur_layer, cur_width, unit_mode=True)
                box_arr = warr.get_bbox_array(grid)
                for box in box_arr:
                    wl, wu = box.get_interval(tr_dir, unit_mode=True)
                    cur_intvs.add((wl - sp, wu + sp), merge=True, abut=True)

        # draw blocks
        nstart = tr_lower // qdim
        nstop = -(-tr_upper // qdim)
        sup_warrs = []
        sup_layer = layer + 1
        for master, intvs in zip((bot_master, top_master), (bot_intvs, top_intvs)):
            sl, su = master.sup_intv
            ncur = nstart
            for nend, nnext in cls._get_blk_idx_iter(intvs, sl, su, qdim, nstart, nstop):
                nblk = nend - ncur
                if nblk > 0:
                    if is_horiz:
                        loc = (ncur * qdim, offset)
                        nx = nblk
                        ny = 1
                    else:
                        loc = (offset, ncur * qdim)
                        nx = 1
                        ny = nblk
                    inst = template.add_instance(master, loc=loc, nx=nx, ny=ny,
                                                 spx=qdim, spy=qdim, unit_mode=True)
                    sup_warrs.extend(inst.port_pins_iter('sup', layer=sup_layer))
                ncur = nnext

        # draw wires and end master
        tr_lower = nstart * qdim
        tr_upper = nstop * qdim
        # draw shields
        tr0_ref = route_tids[0][0]
        sh0 = tr0_ref + tr0
        shp = route_tids[nwire + 1][0] - tr0_ref
        if is_horiz:
            p0 = (tr_lower, offset)
            p1 = (tr_upper, offset)
        else:
            p0 = (offset, tr_lower)
            p1 = (offset, tr_upper)
        template.add_wires(layer, sh0, tr_lower, tr_upper, num=2, pitch=shp, unit_mode=True)
        if lu_end_mode == 0:
            tr_warr_list = template.extend_wires(tr_warr_list, lower=tr_lower, upper=tr_upper,
                                                 unit_mode=True)
        if lu_end_mode != 0:
            end_master = template.new_template(params=params, temp_cls=BiasShieldEnd)
            if lu_end_mode & 2 != 0:
                tr_warr_list = template.extend_wires(tr_warr_list, upper=tr_upper, unit_mode=True)
                eorient = 'MY' if is_horiz else 'MX'
                loc = p0
                p0 = None
            else:
                tr_warr_list = template.extend_wires(tr_warr_list, lower=tr_lower, unit_mode=True)
                eorient = 'R0'
                loc = p1
                p1 = None
            inst = template.add_instance(end_master, loc=loc, orient=eorient, unit_mode=True)
            sup_warrs.extend(inst.get_all_port_pins('sup', layer=sup_layer))

        return BiasInfo(tracks=tr_warr_list, supplies=sup_warrs, p0=p0, p1=p1)

    @classmethod
    def _get_blk_idx_iter(cls, intvs, sl, su, qdim, nstart, nstop):
        # type: (IntervalSet, int, int, int, int, int) -> Generator[Tuple[int, int], None, None]
        for lower, upper in intvs:
            nend = 1 + (lower - su) // qdim
            if nend < nstart:
                raise ValueError('wire interval (%d, %d) is out of bounds.' % (lower, upper))
            ncur = -(-(upper - sl) // qdim)
            yield nend, ncur
        yield nstop, nstop


class BiasShieldEnd(TemplateBase):
    """end cap of bias shield wires.

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
    **kwargs :
        dictionary of optional parameters.  See documentation of
        :class:`bag.layout.template.TemplateBase` for details.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **kwargs) -> None
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)
        self._nblk = None

    @property
    def num_blk(self):
        return self._nblk

    @classmethod
    def get_params_info(cls):
        # type: () -> Dict[str, str]
        return dict(
            layer='the routing layer.',
            nwire='number of routing wires.',
            bias_config='The bias configuration dictionary.',
            width='route wire width.',
            space_sig='route wire spacing.',
        )

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        return dict(
            width=1,
            space_sig=0,
        )

    def get_layout_basename(self):
        layer = self.params['layer']
        nwire = self.params['nwire']
        return 'bias_shield_end_lay%d_n%d' % (layer, nwire)

    def draw_layout(self):
        # type: () -> None
        route_layer = self.params['layer']
        nwire = self.params['nwire']
        width = self.params['width']

        grid = self.grid

        top_layer = route_layer + 1
        route_dir = grid.get_direction(route_layer)
        is_horiz = (route_dir == 'x')

        params = self.params.copy()
        params['top'] = False
        bot_master = self.new_template(params=params, temp_cls=BiasShield)
        params['top'] = True
        top_master = self.new_template(params=params, temp_cls=BiasShield)
        bot_box = bot_master.bound_box
        blk_w = bot_box.width_unit
        blk_h = bot_box.height_unit
        sp_le = grid.get_line_end_space(route_layer, width, unit_mode=True)
        min_len = grid.get_min_length(route_layer, width, unit_mode=True)

        orig = (0, 0)
        nx = ny = 1
        if is_horiz:
            min_len = max(min_len, blk_w)
            nx = nblk = -(-(sp_le + min_len) // blk_w)  # type: int
            cr = nblk * blk_w
        else:
            min_len = max(min_len, blk_h)
            ny = nblk = -(-(sp_le + min_len) // blk_h)  # type: int
            cr = nblk * blk_h
        self._nblk = nblk

        bot_inst = self.add_instance(bot_master, 'XBOT', loc=orig, nx=nx, ny=ny,
                                     spx=blk_w, spy=blk_h, unit_mode=True)
        top_inst = self.add_instance(top_master, 'XTOP', loc=orig, nx=nx, ny=ny,
                                     spx=blk_w, spy=blk_h, unit_mode=True)

        (tidx0, tr_w), (tidx1, _) = bot_master.route_tids[1:3]
        warr = self.add_wires(route_layer, tidx0, cr - min_len, cr, width=tr_w, num=nwire,
                              pitch=tidx1 - tidx0, unit_mode=True)
        bot_port = bot_inst.get_port('sup', row=ny - 1, col=nx - 1)
        top_port = top_inst.get_port('sup', row=ny - 1, col=nx - 1)
        self.connect_to_track_wires(warr, bot_port.get_pins())
        self.connect_to_track_wires(warr, top_port.get_pins())

        bnd_box = bot_inst.bound_box
        self.prim_top_layer = top_layer
        self.prim_bound_box = bnd_box
        self.array_box = bnd_box
        self.add_pin('sup', top_inst.get_all_port_pins('sup'), show=False)


class BiasShieldJoin(TemplateBase):
    """This template joins orthogonal bias routes together.

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
    **kwargs :
        dictionary of optional parameters.  See documentation of
        :class:`bag.layout.template.TemplateBase` for details.
    """

    def __init__(self, temp_db, lib_name, params, used_names, **kwargs):
        # type: (TemplateDB, str, Dict[str, Any], Set[str], **kwargs) -> None
        TemplateBase.__init__(self, temp_db, lib_name, params, used_names, **kwargs)

    @classmethod
    def get_params_info(cls):
        # type: () -> Dict[str, str]
        return dict(
            bot_layer='The bottom routing layer ID.',
            bot_params='the bottom layer routing parameters.',
            top_params='the top layer routing parameters.',
            bot_open='True if bottom layer routing is open on both ends.',
            top_open='True if top layer routing is open on both ends.',
        )

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        return dict(
            bot_open=False,
            top_open=False,
        )

    def draw_layout(self):
        # type: () -> None
        bot_layer = self.params['bot_layer']
        bot_params = self.params['bot_params']
        top_params = self.params['top_params']
        bot_open = self.params['bot_open']
        top_open = self.params['top_open']

        grid = self.grid

        top_layer = bot_layer + 1
        bot_dir = grid.get_direction(bot_layer)
        bot_horiz = (bot_dir == 'x')

        bot_w, bot_h = BiasShield.get_block_size(grid, bot_layer, **bot_params)
        top_w, top_h = BiasShield.get_block_size(grid, top_layer, **top_params)

        nx_bot = ny_bot = nx_top = ny_top = 1
        if bot_horiz:
            nx_bot = nblk_bot = -(-top_w // bot_w)
            ny_top = nblk_top = -(-bot_h // top_h)

        else:
            ny_bot = nblk_bot = -(-top_h // bot_h)
            nx_top = nblk_top = -(-bot_w // top_w)

        bot_params = bot_params.copy()
        bot_params['layer'] = bot_layer
        bot_params['top'] = False
        bb_master = self.new_template(params=bot_params, temp_cls=BiasShield)
        bot_params['top'] = True
        bt_master = self.new_template(params=bot_params, temp_cls=BiasShield)
        top_params = top_params.copy()
        top_params['layer'] = top_layer
        top_params['top'] = True
        tt_master = self.new_template(params=top_params, temp_cls=BiasShield)
        top_params['top'] = False
        tb_master = self.new_template(params=top_params, temp_cls=BiasShield)

        bb_inst = self.add_instance(bb_master, 'XBB', loc=(0, 0), nx=nx_bot,
                                    ny=ny_bot, spx=bot_w, spy=bot_h, unit_mode=True)
        tt_inst = self.add_instance(tt_master, 'XTT', loc=(0, 0), nx=nx_top,
                                    ny=ny_top, spx=top_w, spy=top_h, unit_mode=True)
        bt_test = self.add_instance(bt_master, 'XBT', loc=(0, -bot_h), unit_mode=True)
        tb_test = self.add_instance(tb_master, 'XTB', loc=(-top_w, 0), unit_mode=True)


