"""Camera directions spread as far apart as possible over the sphere.

`spread_directions(n)` solves the Tammes problem numerically: place n unit
vectors so the smallest angle between any two is as large as possible (n=6
gives the octahedron, 90 deg; n=12 the icosahedron, 63.4 deg). Any rotation of
an optimal set is equally optimal, so the set is then turned to sit as far as
possible from the six axis views (top/bottom/front/back/left/right), which
lamad already renders on their own, and ordered from the top down.

A direction points from the model towards the camera.
"""

import math

import numpy as np

AXES = np.vstack([np.eye(3), -np.eye(3)])


def min_angle_deg(dirs):
    """Smallest angle between any two of `dirs`, degrees."""
    d = np.asarray(dirs, dtype=float)
    if len(d) < 2:
        return 180.0
    cos = np.clip(d @ d.T, -1, 1)
    np.fill_diagonal(cos, -1)
    return math.degrees(math.acos(cos.max()))


def _fibonacci(n):
    i = np.arange(n) + 0.5
    z = 1 - 2 * i / n
    r = np.sqrt(1 - z * z)
    phi = i * math.pi * (3 - math.sqrt(5))
    return np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=1)


def _optimise(x, steps=3000):
    """Repulsion with a growing exponent, which tends to max-min spacing,
    then pushes on the closest pairs only to tighten the minimum."""
    n = len(x)
    for t in range(steps):
        k = 2 + 22 * t / steps
        diff = x[:, None, :] - x[None, :, :]
        dist = np.linalg.norm(diff, axis=-1) + np.eye(n)
        dmin = dist[~np.eye(n, dtype=bool)].min()
        force = (diff * ((dmin / dist) ** (k + 2))[..., None]).sum(axis=1)
        force -= (force * x).sum(1, keepdims=True) * x   # tangent part only
        x = x + 0.05 * dmin * force / (np.linalg.norm(force, axis=1, keepdims=True).max() + 1e-12)
        x /= np.linalg.norm(x, axis=1, keepdims=True)
    for t in range(steps):
        cos = x @ x.T
        np.fill_diagonal(cos, -2)
        worst = cos.max()
        i, j = np.argwhere(cos > worst - 1e-6)[:, :2].T
        step = 0.002 * (1 - t / steps) + 1e-5
        push = np.zeros_like(x)
        np.add.at(push, i, x[i] - x[j])
        x = x + step * push
        x /= np.linalg.norm(x, axis=1, keepdims=True)
    return x


def _rotations(count, seed):
    """`count` uniformly random rotation matrices (Shoemake quaternions)."""
    rng = np.random.default_rng(seed)
    u1, u2, u3 = rng.random((3, count))
    q = np.stack([np.sqrt(1 - u1) * np.sin(2 * np.pi * u2), np.sqrt(1 - u1) * np.cos(2 * np.pi * u2),
                  np.sqrt(u1) * np.sin(2 * np.pi * u3), np.sqrt(u1) * np.cos(2 * np.pi * u3)], axis=1)
    x, y, z, w = q.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], axis=1)


def spread_directions(n, seed=0):
    """n unit camera directions with the largest smallest pairwise angle,
    turned away from the axis views and sorted top-down, then by azimuth.
    Deterministic for a given `seed`."""
    if n < 1:
        return np.zeros((0, 3))
    if n == 1:
        return np.array([[1.0, -1.0, 1.0]]) / math.sqrt(3)   # the classic iso view
    x = _optimise(_fibonacci(n))
    rots = _rotations(4000, seed)
    turned = np.einsum("rij,nj->rni", rots, x)
    # Best rotation: largest smallest angle to any axis view.
    score = np.clip(np.abs(turned @ AXES[:3].T), 0, 1).max(axis=(1, 2))
    x = turned[int(np.argmin(score))]
    az = np.degrees(np.arctan2(x[:, 1], x[:, 0])) % 360
    order = np.lexsort((az, -np.round(x[:, 2], 6)))
    return x[order]


def camera(direction):
    """(up, azimuth deg, elevation deg) for a camera looking from `direction`
    at the origin. Up is world +Z projected into the view, or +Y when looking
    straight down or up."""
    d = np.asarray(direction, dtype=float)
    d = d / np.linalg.norm(d)
    ref = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.99 else np.array([0.0, 1.0, 0.0])
    up = ref - (ref @ d) * d
    up /= np.linalg.norm(up)
    return (up, math.degrees(math.atan2(d[1], d[0])) % 360,
            math.degrees(math.asin(max(-1.0, min(1.0, d[2])))))
