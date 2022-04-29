from geographiclib.geodesic import Geodesic

from .units import units


def process_ses(new, key, alpha=0.4):
    forecast = []
    previous = [None]

    def ses(item):
        current = key(item)
        try:
            if forecast:
                predicted = alpha * previous[0] + (1 - alpha) * forecast[-1]
                forecast.append(predicted)
                return {new: predicted}
            else:
                forecast.append(current)
                return {new: current}
        finally:
            previous[0] = current

    return ses


def calculate_speeds():
    def accept(a, b, c):
        assert c == 1
        inverse = Geodesic.WGS84.Inverse(a.point.lat, a.point.lon, b.point.lat, b.point.lon)
        dist = units.Quantity(inverse['s12'], units.m)
        time = units.Quantity((b.dt - a.dt).total_seconds(), units.seconds)
        raw_azi = inverse['azi1']
        azi = units.Quantity(raw_azi, units.degree)

        raw_cog = 0 + raw_azi if raw_azi >= 0 else 360 + raw_azi
        cog = units.Quantity(raw_cog, units.degree)

        speed = dist / time

        return {
            "cspeed": speed,
            "dist": dist,
            "time": time,
            "azi": azi,
            "cog": cog
        }

    return accept


def calculate_odo():
    total = [units.Quantity(0.0, units.m)]

    def accept(e):
        if e.dist is not None:
            total[0] += e.dist
        return {"odo": total[0]}

    return accept


def calculate_gradient():
    def accept(a, b, c):
        if a.alt is None or b.alt is None:
            return {"grad": 0.0}
        gain = b.alt - a.alt
        if a.odo and b.odo:
            dist = b.odo - a.odo
            if dist and dist.magnitude > 0:
                return {"grad": (gain / dist) * 100.0}

    return accept
