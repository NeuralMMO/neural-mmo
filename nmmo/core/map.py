import numpy as np
from ordered_set import OrderedSet

from nmmo.core.tile import Tile
from nmmo.lib import material, utils
from nmmo.core.terrain import (
  fractal_to_material,
  process_map_border,
  spawn_profession_resources,
)


class Map:
  '''Map object representing a list of tiles

  Also tracks a sparse list of tile updates
  '''
  def __init__(self, config, realm, np_random):
    self.config = config
    self._repr  = None
    self.realm  = realm
    self.update_list = None
    self.pathfinding_cache = {} # Avoid recalculating A*, paths don't move

    sz          = config.MAP_SIZE
    self.tiles  = np.zeros((sz,sz), dtype=object)
    self.habitable_tiles = np.zeros((sz,sz))

    for r in range(sz):
      for c in range(sz):
        self.tiles[r, c] = Tile(realm, r, c, np_random)

    self.dist_border_center = None
    self.center_coord = None

    # used to place border
    self.l1 = utils.l1_map(sz)

  @property
  def packet(self):
    '''Packet of degenerate resource states'''
    missing_resources = []
    for e in self.update_list:
      missing_resources.append(e.pos)
    return missing_resources

  @property
  def repr(self):
    '''Flat matrix of tile material indices'''
    if not self._repr:
      self._repr = [[t.material.index for t in row] for row in self.tiles]
    return self._repr

  def reset(self, map_dict, np_random):
    '''Reuse the current tile objects to load a new map'''
    config = self.config
    assert map_dict["map"].shape == (config.MAP_SIZE,config.MAP_SIZE),\
      "Map shape is inconsistent with config.MAP_SIZE"

    # NOTE: MAP_CENTER and MAP_BORDER can change from episode to episode
    self.dist_border_center = config.MAP_CENTER // 2
    self.center_coord = (config.MAP_BORDER + self.dist_border_center,
                         config.MAP_BORDER + self.dist_border_center)
    assert config.MAP_BORDER > config.PLAYER_VISION_RADIUS,\
      "MAP_BORDER must be greater than PLAYER_VISION_RADIUS"

    self._repr = None
    self.update_list = OrderedSet() # critical for determinism
    materials = {mat.index: mat for mat in material.All}

    # process map_np_array according to config
    matl_map = self._process_map(map_dict, np_random)

    # reset tiles with new materials
    for r, row in enumerate(matl_map):
      for c, idx in enumerate(row):
        mat = materials[idx]
        tile = self.tiles[r, c]
        tile.reset(mat, config, np_random)
        self.habitable_tiles[r, c] = tile.habitable

  def _process_map(self, map_dict, np_random):
    map_np_array = map_dict["map"]
    if not self.config.TERRAIN_SYSTEM_ENABLED:
      map_np_array[:] = material.Grass.index
    else:
      if self.config.MAP_RESET_FROM_FRACTAL:
        map_tiles = fractal_to_material(self.config, map_dict["fractal"], self.l1)
        # Place materials here, before converting map_tiles into an int array
        if self.config.PROFESSION_SYSTEM_ENABLED:
          spawn_profession_resources(self.config, map_tiles, np_random)
        map_np_array = map_tiles.astype(int)

      # Disable materials here
      if self.config.TERRAIN_DISABLE_STONE:
        map_np_array[map_np_array == material.Stone.index] = material.Grass.index

    # Make the edge tiles habitable, and place the void tiles outside the border
    map_np_array = process_map_border(self.config, map_np_array, self.l1)
    return map_np_array

  def step(self):
    '''Evaluate updatable tiles'''
    for tile in self.update_list.copy():
      if not tile.depleted:
        self.update_list.remove(tile)
      tile.step()

  def harvest(self, r, c, deplete=True):
    '''Called by actions that harvest a resource tile'''

    if deplete:
      self.update_list.add(self.tiles[r, c])

    return self.tiles[r, c].harvest(deplete)

  def is_valid_pos(self, row, col):
    '''Check if a position is valid'''
    return 0 <= row < self.config.MAP_SIZE and 0 <= col < self.config.MAP_SIZE
