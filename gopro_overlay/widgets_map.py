import math

import geotiler
from PIL import ImageDraw, Image

from .journey import Journey
from .privacy import NoPrivacyZone


class PerceptibleMovementCheck:

    def __init__(self):
        self.last_location = None

    def moved(self, map, location):
        location_of_centre_pixel = map.geocode((map.size[0] / 2, map.size[1] / 2))
        location_of_one_pixel_away = map.geocode(((map.size[0] / 2) + 1, (map.size[1] / 2) + 1))

        x_resolution = abs(location_of_one_pixel_away[0] - location_of_centre_pixel[0])
        y_resolution = abs(location_of_one_pixel_away[1] - location_of_centre_pixel[1])

        if self.last_location is not None:
            x_diff = abs(self.last_location.lon - location.lon)
            y_diff = abs(self.last_location.lat - location.lat)

            if x_diff < x_resolution and y_diff < y_resolution:
                return False

        self.last_location = location
        return True


class MaybeRoundedBorder:

    def __init__(self, size, corner_radius, opacity):
        self.opacity = opacity
        self.corner_radius = corner_radius
        self.size = size
        self.mask = None

    def rounded(self, image):

        draw = ImageDraw.Draw(image)

        if self.corner_radius:
            if self.mask is None:
                self.mask = self.generate_mask()

            image.putalpha(self.mask)

            draw.rounded_rectangle(
                (0, 0) + (self.size - 1, self.size - 1),
                radius=self.corner_radius,
                outline=(0, 0, 0)
            )
        else:
            draw.line(
                (0, 0, 0, self.size - 1, self.size - 1, self.size - 1, self.size - 1, 0, 0, 0),
                fill=(0, 0, 0)
            )
            image.putalpha(int(255 * self.opacity))

        return image

    def generate_mask(self):
        mask = Image.new('L', (self.size, self.size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0) + (self.size - 1, self.size - 1), radius=self.corner_radius,
                                               fill=int(self.opacity * 255))
        return mask


class JourneyMap:
    def __init__(self, timeseries, at, location, renderer, size=256, corner_radius=None, opacity=0.7,
                 privacy_zone=NoPrivacyZone()):
        self.timeseries = timeseries
        self.privacy_zone = privacy_zone
        self.at = at
        self.location = location
        self.renderer = renderer
        self.size = size
        self.border = MaybeRoundedBorder(size=size, corner_radius=corner_radius, opacity=opacity)
        self.map = None
        self.image = None

    def _init_maybe(self):
        if self.map is None:
            journey = Journey()

            self.timeseries.process(journey.accept)

            bbox = journey.bounding_box
            self.map = geotiler.Map(extent=(bbox[0].lon, bbox[0].lat, bbox[1].lon, bbox[1].lat),
                                    size=(self.size, self.size))

            if self.map.zoom > 18:
                self.map.zoom = 18

            plots = [
                self.map.rev_geocode((location.lon, location.lat))
                for location in journey.locations if not self.privacy_zone.encloses(location)
            ]

            image = self.renderer(self.map)

            draw = ImageDraw.Draw(image)
            draw.line(plots, fill=(255, 0, 0), width=4)

            self.image = self.border.rounded(image)

    def draw(self, image, draw):
        self._init_maybe()

        frame = self.image.copy()
        draw = ImageDraw.Draw(frame)

        location = self.location()
        if location:
            current = self.map.rev_geocode((location.lon, location.lat))
            draw_marker(draw, current, 6)

        image.alpha_composite(frame, self.at.tuple())


def draw_marker(draw, position, size, fill=None):
    fill = fill if fill is not None else (0, 0, 255)
    draw.ellipse([(position[0] - size, position[1] - size), (position[0] + size, position[1] + size)],
                 fill=fill,
                 outline=(0, 0, 0))


class MovingMap:
    def __init__(self, at, location, azimuth, renderer,
                 rotate=True, size=256, zoom=17, corner_radius=None, opacity=0.7):
        self.at = at
        self.rotate = rotate
        self.azimuth = azimuth
        self.renderer = renderer
        self.location = location
        self.size = size
        self.zoom = zoom
        self.hypotenuse = int(math.sqrt((self.size ** 2) * 2))

        self.half_width_height = (self.hypotenuse / 2)

        self.bounds = (
            self.half_width_height - (self.size / 2),
            self.half_width_height - (self.size / 2),
            self.half_width_height + (self.size / 2),
            self.half_width_height + (self.size / 2)
        )
        self.perceptible = PerceptibleMovementCheck()
        self.border = MaybeRoundedBorder(size=size, corner_radius=corner_radius, opacity=opacity)
        self.cached = None

    def _redraw(self, map):
        image = self.renderer(map)

        draw = ImageDraw.Draw(image)
        draw_marker(draw, (self.half_width_height, self.half_width_height), 6)
        azimuth = self.azimuth()
        if azimuth and self.rotate:
            azi = azimuth.to("degree").magnitude
            angle = 0 + azi if azi >= 0 else 360 + azi
            image = image.rotate(angle)

        crop = image.crop(self.bounds)

        return self.border.rounded(crop)

    def draw(self, image, draw):
        location = self.location()
        if location.lon is not None and location.lat is not None:

            map = geotiler.Map(center=(location.lon, location.lat), zoom=self.zoom,
                               size=(self.hypotenuse, self.hypotenuse))

            if self.perceptible.moved(map, location):
                self.cached = self._redraw(map)

            image.alpha_composite(self.cached, self.at.tuple())


def view_window(size, d):
    def f(n):
        start = max(0, min(d - size, n - int(size / 2)))
        end = start + size
        return start, end

    return f


class MovingJourneyMap:

    def __init__(self, timeseries, privacy_zone, location, size, zoom, renderer):
        self.privacy_zone = privacy_zone
        self.timeseries = timeseries
        self.size = size
        self.renderer = renderer
        self.zoom = zoom
        self.location = location

        self.cached_map_image = None
        self.cached_map = None

    def _redraw(self):
        journey = Journey()
        self.timeseries.process(journey.accept)

        bbox_min, bbox_max = journey.bounding_box

        map = geotiler.Map(
            extent=(
                bbox_min.lon, bbox_min.lat,
                bbox_max.lon, bbox_max.lat
            ),
            zoom=self.zoom
        )

        # add self.size / 2 to eash side of the map, so adding self.size overall
        map.size = (map.size[0] + self.size), (map.size[1] + self.size)

        print(f"{self.__class__.__name__} Rendering backing map ({map.size}) (can be slow)", end="")

        map_image = self.renderer(map)

        print(f"... done")

        plots = [
            map.rev_geocode((location.lon, location.lat))
            for location in journey.locations if not self.privacy_zone.encloses(location)
        ]

        draw = ImageDraw.Draw(map_image)
        draw.line(plots, fill=(255, 0, 0), width=4)

        return map, map_image

    def draw(self, image, draw):
        if self.cached_map is None:
            self.cached_map, self.cached_map_image = self._redraw()

        location = self.location()
        if location.lon is not None and location.lat is not None:
            current_position_in_big_map = self.cached_map.rev_geocode((location.lon, location.lat))

            map_size = self.cached_map_image.size

            lr = view_window(self.size, map_size[0])(int(current_position_in_big_map[0]))
            tb = view_window(self.size, map_size[1])(int(current_position_in_big_map[1]))

            image.alpha_composite(self.cached_map_image, (0, 0), source=(lr[0], tb[0], lr[1], tb[1]))
            draw_marker(draw, (int(self.size / 2), int(self.size / 2)), 6)
