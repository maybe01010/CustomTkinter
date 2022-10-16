import tkinter
from distutils.version import StrictVersion as Version
import sys
import os
import platform
import ctypes
import re
from typing import Union, Tuple

from ..appearance_mode_tracker import AppearanceModeTracker
from ..theme_manager import ThemeManager
from ..scaling_tracker import ScalingTracker
from ..settings import Settings

from ..utility.utility_functions import pop_from_dict_by_set, check_kwargs_empty


class CTk(tkinter.Tk):
    """
    Main app window with dark titlebar on Windows and macOS.
    For detailed information check out the documentation.
    """

    _valid_tk_constructor_arguments = {"screenName", "baseName", "className", "useTk", "sync", "use"}

    _valid_tk_configure_arguments = {'bd', 'borderwidth', 'class', 'menu', 'relief', 'screen',
                                     'use', 'container', 'cursor', 'height',
                                     'highlightthickness', 'padx', 'pady', 'takefocus', 'visual', 'width'}

    def __init__(self,
                 fg_color: Union[str, Tuple[str, str]] = "default_theme",
                 **kwargs):

        ScalingTracker.activate_high_dpi_awareness()  # make process DPI aware
        self._enable_macos_dark_title_bar()

        super().__init__(**pop_from_dict_by_set(kwargs, self._valid_tk_constructor_arguments))
        check_kwargs_empty(kwargs, raise_error=True)

        # add set_appearance_mode method to callback list of AppearanceModeTracker for appearance mode changes
        AppearanceModeTracker.add(self._set_appearance_mode, self)
        self._appearance_mode = AppearanceModeTracker.get_mode()  # 0: "Light" 1: "Dark"

        # add set_scaling method to callback list of ScalingTracker for automatic scaling changes
        ScalingTracker.add_widget(self._set_scaling, self)
        self._window_scaling = ScalingTracker.get_window_scaling(self)

        self._current_width = 600  # initial window size, always without scaling
        self._current_height = 500
        self._min_width: int = 0
        self._min_height: int = 0
        self._max_width: int = 1_000_000
        self._max_height: int = 1_000_000
        self._last_resizable_args: Union[Tuple[list, dict], None] = None  # (args, kwargs)

        self._fg_color = ThemeManager.theme["color"]["window_bg_color"] if fg_color == "default_theme" else fg_color

        super().configure(bg=ThemeManager.single_color(self._fg_color, self._appearance_mode))
        super().title("CTk")
        self.geometry(f"{self._current_width}x{self._current_height}")

        self._state_before_windows_set_titlebar_color = None
        self._window_exists = False  # indicates if the window is already shown through update() or mainloop() after init
        self._withdraw_called_before_window_exists = False  # indicates if withdraw() was called before window is first shown through update() or mainloop()
        self._iconify_called_before_window_exists = False  # indicates if iconify() was called before window is first shown through update() or mainloop()

        if sys.platform.startswith("win"):
            if self._appearance_mode == 1:
                self._windows_set_titlebar_color("dark")
            else:
                self._windows_set_titlebar_color("light")

        self.bind('<Configure>', self._update_dimensions_event)
        self.bind('<FocusIn>', self._focus_in_event)

        self._block_update_dimensions_event = False

    def _focus_in_event(self, event):
        # sometimes window looses focus on macOS if window is selected from Mission Control, so focus has to be forced again
        if sys.platform == "darwin":
            self.focus_force()

    def _update_dimensions_event(self, event=None):
        if not self._block_update_dimensions_event:
            self.update_idletasks()
            detected_width = self.winfo_width()  # detect current window size
            detected_height = self.winfo_height()

            if self._current_width != round(detected_width / self._window_scaling) or self._current_height != round(detected_height / self._window_scaling):
                self._current_width = round(detected_width / self._window_scaling)  # adjust current size according to new size given by event
                self._current_height = round(detected_height / self._window_scaling)  # _current_width and _current_height are independent of the scale

    def _set_scaling(self, new_widget_scaling, new_spacing_scaling, new_window_scaling):
        self._window_scaling = new_window_scaling

        # block update_dimensions_event to prevent current_width and current_height to get updated
        self._block_update_dimensions_event = True

        # force new dimensions on window by using min, max, and geometry
        super().minsize(self._apply_window_scaling(self._current_width), self._apply_window_scaling(self._current_height))
        super().maxsize(self._apply_window_scaling(self._current_width), self._apply_window_scaling(self._current_height))

        super().geometry(f"{self._apply_window_scaling(self._current_width)}x{self._apply_window_scaling(self._current_height)}")

        # set new scaled min and max with 400ms delay (otherwise it won't work for some reason)
        self.after(400, self._set_scaled_min_max)

        # release the blocking of update_dimensions_event after a small amount of time (slight delay is necessary)
        def set_block_update_dimensions_event_false():
            self._block_update_dimensions_event = False
        self.after(100, lambda: set_block_update_dimensions_event_false())

    def _set_scaled_min_max(self):
        if self._min_width is not None or self._min_height is not None:
            super().minsize(self._apply_window_scaling(self._min_width), self._apply_window_scaling(self._min_height))
        if self._max_width is not None or self._max_height is not None:
            super().maxsize(self._apply_window_scaling(self._max_width), self._apply_window_scaling(self._max_height))

    def destroy(self):
        AppearanceModeTracker.remove(self._set_appearance_mode)
        ScalingTracker.remove_window(self._set_scaling, self)
        self._disable_macos_dark_title_bar()
        super().destroy()

    def withdraw(self):
        if self._window_exists is False:
            self._withdraw_called_before_window_exists = True
        super().withdraw()

    def iconify(self):
        if self._window_exists is False:
            self._iconify_called_before_window_exists = True
        super().iconify()

    def update(self):
        if self._window_exists is False:
            self._window_exists = True

            if sys.platform.startswith("win"):
                if not self._withdraw_called_before_window_exists and not self._iconify_called_before_window_exists:
                    # print("window dont exists -> deiconify in update")
                    self.deiconify()

        super().update()

    def mainloop(self, *args, **kwargs):
        if not self._window_exists:
            self._window_exists = True

            if sys.platform.startswith("win"):
                if not self._withdraw_called_before_window_exists and not self._iconify_called_before_window_exists:
                    # print("window dont exists -> deiconify in mainloop")
                    self.deiconify()

        super().mainloop(*args, **kwargs)

    def resizable(self, width: bool = None, height: bool = None):
        super().resizable(width, height)
        self._last_resizable_args = ([], {"width": width, "height": height})

        if sys.platform.startswith("win"):
            if self._appearance_mode == 1:
                self._windows_set_titlebar_color("dark")
            else:
                self._windows_set_titlebar_color("light")

    def minsize(self, width=None, height=None):
        self._min_width = width
        self._min_height = height
        if self._current_width < width:
            self._current_width = width
        if self._current_height < height:
            self._current_height = height
        super().minsize(self._apply_window_scaling(self._min_width), self._apply_window_scaling(self._min_height))

    def maxsize(self, width=None, height=None):
        self._max_width = width
        self._max_height = height
        if self._current_width > width:
            self._current_width = width
        if self._current_height > height:
            self._current_height = height
        super().maxsize(self._apply_window_scaling(self._max_width), self._apply_window_scaling(self._max_height))

    def geometry(self, geometry_string: str = None):
        if geometry_string is not None:
            super().geometry(self._apply_geometry_scaling(geometry_string))

            # update width and height attributes
            width, height, x, y = self._parse_geometry_string(geometry_string)
            if width is not None and height is not None:
                self._current_width = max(self._min_width, min(width, self._max_width))  # bound value between min and max
                self._current_height = max(self._min_height, min(height, self._max_height))
        else:
            return self._reverse_geometry_scaling(super().geometry())

    @staticmethod
    def _parse_geometry_string(geometry_string: str) -> tuple:
        #                 index:   1                   2           3          4             5       6
        # regex group structure: ('<width>x<height>', '<width>', '<height>', '+-<x>+-<y>', '-<x>', '-<y>')
        result = re.search(r"((\d+)x(\d+)){0,1}(\+{0,1}([+-]{0,1}\d+)\+{0,1}([+-]{0,1}\d+)){0,1}", geometry_string)

        width = int(result.group(2)) if result.group(2) is not None else None
        height = int(result.group(3)) if result.group(3) is not None else None
        x = int(result.group(5)) if result.group(5) is not None else None
        y = int(result.group(6)) if result.group(6) is not None else None

        return width, height, x, y

    def _apply_geometry_scaling(self, geometry_string: str) -> str:
        width, height, x, y = self._parse_geometry_string(geometry_string)

        if x is None and y is None:  # no <x> and <y> in geometry_string
            return f"{round(width * self._window_scaling)}x{round(height * self._window_scaling)}"

        elif width is None and height is None:  # no <width> and <height> in geometry_string
            return f"+{x}+{y}"

        else:
            return f"{round(width * self._window_scaling)}x{round(height * self._window_scaling)}+{x}+{y}"

    def _reverse_geometry_scaling(self, scaled_geometry_string: str) -> str:
        width, height, x, y = self._parse_geometry_string(scaled_geometry_string)

        if x is None and y is None:  # no <x> and <y> in geometry_string
            return f"{round(width / self._window_scaling)}x{round(height / self._window_scaling)}"

        elif width is None and height is None:  # no <width> and <height> in geometry_string
            return f"+{x}+{y}"

        else:
            return f"{round(width / self._window_scaling)}x{round(height / self._window_scaling)}+{x}+{y}"

    def _apply_window_scaling(self, value):
        if isinstance(value, (int, float)):
            return int(value * self._window_scaling)
        else:
            return value

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            self._fg_color = kwargs.pop("fg_color")
            super().configure(bg=ThemeManager.single_color(self._fg_color, self._appearance_mode))

            for child in self.winfo_children():
                try:
                    child.configure(bg_color=self._fg_color)
                except Exception:
                    pass

        super().configure(**pop_from_dict_by_set(kwargs, self._valid_tk_configure_arguments))
        check_kwargs_empty(kwargs)

    def cget(self, attribute_name: str) -> any:
        if attribute_name == "fg_color":
            return self._fg_color
        else:
            return super().cget(attribute_name)

    @staticmethod
    def _enable_macos_dark_title_bar():
        if sys.platform == "darwin" and not Settings.deactivate_macos_window_header_manipulation:  # macOS
            if Version(platform.python_version()) < Version("3.10"):
                if Version(tkinter.Tcl().call("info", "patchlevel")) >= Version("8.6.9"):  # Tcl/Tk >= 8.6.9
                    os.system("defaults write -g NSRequiresAquaSystemAppearance -bool No")
                    # This command allows dark-mode for all programs

    @staticmethod
    def _disable_macos_dark_title_bar():
        if sys.platform == "darwin" and not Settings.deactivate_macos_window_header_manipulation:  # macOS
            if Version(platform.python_version()) < Version("3.10"):
                if Version(tkinter.Tcl().call("info", "patchlevel")) >= Version("8.6.9"):  # Tcl/Tk >= 8.6.9
                    os.system("defaults delete -g NSRequiresAquaSystemAppearance")
                    # This command reverts the dark-mode setting for all programs.

    def _windows_set_titlebar_color(self, color_mode: str):
        """
        Set the titlebar color of the window to light or dark theme on Microsoft Windows.

        Credits for this function:
        https://stackoverflow.com/questions/23836000/can-i-change-the-title-bar-in-tkinter/70724666#70724666

        MORE INFO:
        https://docs.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
        """

        if sys.platform.startswith("win") and not Settings.deactivate_windows_window_header_manipulation:

            if self._window_exists:
                self._state_before_windows_set_titlebar_color = self.state()
                # print("window_exists -> state_before_windows_set_titlebar_color: ", self.state_before_windows_set_titlebar_color)

                if self._state_before_windows_set_titlebar_color != "iconic" or self._state_before_windows_set_titlebar_color != "withdrawn":
                    super().withdraw()  # hide window so that it can be redrawn after the titlebar change so that the color change is visible
            else:
                # print("window dont exists -> withdraw and update")
                super().withdraw()
                super().update()

            if color_mode.lower() == "dark":
                value = 1
            elif color_mode.lower() == "light":
                value = 0
            else:
                return

            try:
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19

                # try with DWMWA_USE_IMMERSIVE_DARK_MODE
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                                              ctypes.byref(ctypes.c_int(value)),
                                                              ctypes.sizeof(ctypes.c_int(value))) != 0:

                    # try with DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20h1
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
                                                               ctypes.byref(ctypes.c_int(value)),
                                                               ctypes.sizeof(ctypes.c_int(value)))

            except Exception as err:
                print(err)

            if self._window_exists:
                # print("window_exists -> return to original state: ", self.state_before_windows_set_titlebar_color)
                if self._state_before_windows_set_titlebar_color == "normal":
                    self.deiconify()
                elif self._state_before_windows_set_titlebar_color == "iconic":
                    self.iconify()
                elif self._state_before_windows_set_titlebar_color == "zoomed":
                    self.state("zoomed")
                else:
                    self.state(self._state_before_windows_set_titlebar_color)  # other states
            else:
                pass  # wait for update or mainloop to be called

    def _set_appearance_mode(self, mode_string):
        if mode_string.lower() == "dark":
            self._appearance_mode = 1
        elif mode_string.lower() == "light":
            self._appearance_mode = 0

        if sys.platform.startswith("win"):
            if self._appearance_mode == 1:
                self._windows_set_titlebar_color("dark")
            else:
                self._windows_set_titlebar_color("light")

        super().configure(bg=ThemeManager.single_color(self._fg_color, self._appearance_mode))
