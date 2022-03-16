import random
from datetime import timedelta

from PIL import ImageFont, Image, ImageDraw

from gopro_overlay import fake
from gopro_overlay.dimensions import Dimension
from gopro_overlay.widgets_asi import Arc, scale, roundup
from tests.approval import approve_image
from tests.test_widgets import time_rendering

font = ImageFont.truetype(font='Roboto-Medium.ttf', size=18)
title_font = font.font_variant(size=16)

# Need reproducible results for approval tests
rng = random.Random()
rng.seed(12345)

ts = fake.fake_timeseries(timedelta(minutes=10), step=timedelta(seconds=1), rng=rng)


class Speedometer:

    def __init__(self, size, font, reading, rotate=0):

        rotate = (rotate + 180)

        self.value_max = 30
        self.value_min = 0
        self.font = font
        self.reading = reading

        self.step = 5

        self.gauge_max = roundup((self.value_max - self.value_min) * 0.05 + self.value_max, self.step * 4)

        self.size = size
        self.bg = None
        self.fg = (255, 255, 255)
        self.text = (255, 255, 255)

        self.xa = scale(self.value_min, self.gauge_max, rotate)

        self.image = None

    def draw_asi(self):

        image = Image.new(mode="RGBA", size=(self.size, self.size))
        draw = ImageDraw.Draw(image)

        def ticklenwidth(value):
            if value % 10 == 0:
                return 33, 2
            return 27, 1

        arc = Arc(self.size)

        arc.pieslice(draw, 0, outline=(0, 0, 0, 128), fill=(0, 0, 0, 128), width=2)

        for value in range(self.value_min, self.gauge_max + self.step, self.step):
            ticklen, width = ticklenwidth(value)
            arc.line(draw, [(self.xa(value), ticklen), (self.xa(value), 0)], fill=self.fg, width=width)

        for value in range(self.value_min, self.gauge_max + (self.step * 4), self.step * 4):
            draw.text(
                arc.locate(self.xa(value), int(self.size / 4.5)),
                str(value),
                font=self.font,
                anchor="mm",
                fill=self.text
            )

        return image

    def draw(self, image, draw):

        if self.image is None:
            self.image = self.draw_asi()

        image.alpha_composite(self.image, (0, 0))

        reading = self.reading()

        if reading < self.value_min:
            reading = self.value_min - 1

        if reading < 0:
            reading = 0

        arc = Arc(self.size)

        draw.polygon(
            [
                arc.locate(self.xa(reading) - 0, 0),
                arc.locate(self.xa(reading) - 90, (self.size / 2) - 8),
                arc.locate(self.xa(reading) - 180, (self.size / 2) - 8),
                arc.locate(self.xa(reading) + 90, (self.size / 2) - 8),
            ],
            fill=self.fg,
            outline=(0,0,0)
        )


@approve_image
def test_speedo():
    size = 256
    return time_rendering(
        name="test_speedo",
        dimensions=Dimension(size, size),
        widgets=[
            Speedometer(size=256, font=font, reading=lambda: 23)
        ]
    )
