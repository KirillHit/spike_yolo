from matplotlib import pyplot as plt
import collections


class ProgressBoard:
    """The board that plots data points in animation."""

    def __init__(
        self,
        xlabel: str = None,
        ylabel: str = None,
        ylim: tuple[float, float] = (1.0, 0.1),
        xscale: str = "linear",
        yscale: str = "linear",
        ls: list[str] = ["-", "--", "-.", ":"],
        colors: list[str] = ["C0", "C1", "C2", "C3"],
        figsize: tuple[int, int] = (6, 6),
        display: bool = True,
        every_n: int = 1,
    ):
        self.ls, self.colors, self.display, self.every_n = ls, colors, display, every_n
        if not self.display:
            return
        plt.ion()
        subplot = plt.subplots(figsize=figsize)
        self.fig = subplot[0]
        self.axes: plt.Axes = subplot[1]
        self.axes.set_xlabel(xlabel)
        self.axes.set_ylabel(ylabel)
        self.axes.set_xscale(xscale)
        self.axes.set_yscale(yscale)
        self.axes.set_ylim(top=ylim[0], bottom=ylim[1])
        self.raw_points = collections.OrderedDict()
        self.data = collections.OrderedDict()
        self.lines = {}

    def draw(self, x, y, label: str):
        if not self.display:
            return

        Point = collections.namedtuple("Point", ["x", "y"])

        if label not in self.raw_points:
            self.raw_points[label] = []
            self.data[label] = []
        points = self.raw_points[label]
        linep = self.data[label]

        points.append(Point(x, y))
        if len(points) != self.every_n:
            return

        mean = lambda x: sum(x) / len(x)
        linep.append(Point(mean([p.x for p in points]), mean([p.y for p in points])))
        points.clear()

        if label not in self.lines:
            (line,) = self.axes.plot(
                linep[0].x,
                linep[0].y,
                linestyle=self.ls[len(self.lines) % 4],
                color=self.colors[len(self.lines) % 4],
            )
            self.lines[label] = line
            return

        self.lines[label].set_xdata([p.x for p in linep])
        self.lines[label].set_ydata([p.y for p in linep])
        self.lines[label].set_ydata([p.y for p in linep])
        left, right = self.axes.get_xlim()
        self.axes.set_xlim(
            left if linep[-1].x > left else linep[-1].x,
            right if linep[-1].x < right else linep[-1].x,
        )
        bottom, top = self.axes.get_ylim()
        self.axes.set_ylim(
            bottom if linep[-1].y > bottom else linep[-1].y,
            top if linep[-1].y < top else linep[-1].y,
        )
        self.axes.legend(self.lines.values(), self.lines.keys())

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()