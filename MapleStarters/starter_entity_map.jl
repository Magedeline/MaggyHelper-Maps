using Maple

# Tiny starter using entityMap shorthand markers:
# P = Player, R = Strawberry, Q = DashRefill
layout = """
3333333333333333
3              3
3      R       3
3              3
3   Q          3
3              3
3P             3
3333333333333333
"""

fg_tiles = FgTiles(layout)

map = Map(
    "Maggy/MapleStarterEntity",
    Room[
        Room(
            name = "entity_start",
            fgTiles = fg_tiles,
            position = (0, 0),
            size = size(fg_tiles),
            entities = entityMap(layout),
        )
    ]
)

workspace_root = normpath(joinpath(@__DIR__, ".."))
out_path = joinpath(workspace_root, "Maps", "Maggy", "MapleStarterEntity.bin")

mkpath(dirname(out_path))
encodeMap(map, out_path)
println("Wrote: " * out_path)
