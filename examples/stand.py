# Phone stand: an angled cradle with a retaining lip.
width = 80      # side to side
depth = 50      # front to back
angle = 60      # lean from horizontal, degrees
thick = 6       # material thickness
lip = 5         # front lip height

import math
rise = depth * math.tan(math.radians(angle))

# Wedge: right triangle (depth x rise) extruded across the width,
# then stood upright so the slope faces front.
wedge = Rot(90, 0, 0) * extrude(
    Polygon((0, 0), (depth, 0), (0, rise), align=None), amount=width
)
wedge = Pos(-depth / 2, width / 2, 0) * wedge

# Hollow it out so it prints as a shell, not a brick.
inner = Rot(90, 0, 0) * extrude(
    Polygon((thick * 2, thick), (depth - thick, thick),
            (thick * 2, rise - thick * 3), align=None),
    amount=width - thick * 2,
)
wedge = wedge - (Pos(-depth / 2, (width - thick * 2) / 2, 0) * inner)

# Cradle floor and the lip that stops the phone sliding off.
floor = Pos(depth / 2 - thick / 2, 0, thick / 2) * Box(thick, width, thick)
front = Pos(depth / 2 - thick / 2, 0, thick + lip / 2) * Box(thick, width, lip)

show_object(wedge, name="wedge", color="steelblue")
show_object(floor, name="floor", color="gray")
show_object(front, name="lip", color="orange")
