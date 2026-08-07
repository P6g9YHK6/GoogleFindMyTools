from webui.geo import haversine_distance_m


def test_same_point_is_zero_distance():
    assert haversine_distance_m(45.0, 9.0, 45.0, 9.0) == 0.0


def test_one_degree_of_latitude_is_roughly_111km():
    distance = haversine_distance_m(0.0, 0.0, 1.0, 0.0)
    assert 110_000 < distance < 112_000


def test_known_short_hop_is_reasonably_accurate():
    # Two points ~100m apart (roughly 0.0009 degrees of latitude).
    distance = haversine_distance_m(45.0, 9.0, 45.0009, 9.0)
    assert 95 < distance < 105
