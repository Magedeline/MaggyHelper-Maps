using Maple

# Two-room tiny route starter.
# Room 1 has the player spawn and a refill, Room 2 has a strawberry.
room1 = """
3333333333333333
3              3
3              3
3               
3   Q           
3              3
3P             3
3333333333333333
"""

room2 = """
3333333333333333
3              3
3              3
               3
3          R   3
3              3
3              3
3333333333333333
"""

fg1 = FgTiles(room1)
fg2 = FgTiles(room2)

room_size = size(fg1)

map = Map(
    "Maggy/MapleStarterRoute",
    Room[
        Room(
            name = "route_start",
            fgTiles = fg1,
            position = (0, 0),
            size = room_size,
            entities = entityMap(room1),
        ),
        Room(
            name = "route_berry",
            fgTiles = fg2,
            position = (room_size[1], 0),
            size = size(fg2),
            entities = entityMap(room2),
        ),
    ]
)

workspace_root = normpath(joinpath(@__DIR__, ".."))
out_path = joinpath(workspace_root, "Maps", "Maggy", "MapleStarterRoute.bin")

mkpath(dirname(out_path))
encodeMap(map, out_path)
println("Wrote: " * out_path)
