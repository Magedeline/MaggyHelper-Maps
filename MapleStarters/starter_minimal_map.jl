using Maple

# Tiny starter: one room, one spawn, one checkpoint.
fg = """
3333333333333333
3              3
3              3
3              3
3              3
3              3
3              3
3333333333333333
"""

fg_tiles = FgTiles(fg)

map = Map(
    "Maggy/MapleStarter",
    Room[
        Room(
            name = "start",
            fgTiles = fg_tiles,
            position = (0, 0),
            size = size(fg_tiles),
            entities = Entity[
                Player(16, 40),
                ChapterCheckpoint(16, 40),
            ],
        )
    ]
)

workspace_root = normpath(joinpath(@__DIR__, ".."))
out_path = joinpath(workspace_root, "Maps", "Maggy", "MapleStarter.bin")

mkpath(dirname(out_path))
encodeMap(map, out_path)
println("Wrote: " * out_path)
