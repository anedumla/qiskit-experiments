# This code is part of Qiskit.
#
# (C) Copyright IBM 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
A library of parameter guess functions.
"""
# pylint: disable=invalid-name

import functools
from typing import Optional, Tuple, Callable

import numpy as np
from scipy import signal

from qiskit_experiments.exceptions import AnalysisError


def frequency(x: np.ndarray, y: np.ndarray) -> float:
    """Get frequency of oscillating signal.

    .. note::

        This function returns always positive frequency.

    Args:
        x: Array of x values.
        y: Array of y values.

    Returns:
        Frequency estimation of oscillation signal.
    """
    sampling_rates = np.unique(np.diff(x))
    sampling_rates = sampling_rates[sampling_rates > 0]

    if len(sampling_rates) != 1:
        sampling_rate = np.min(sampling_rates)
        x_ = np.arange(x[0], x[-1], sampling_rate)
        y_ = np.interp(x_, xp=x, fp=y)
    else:
        sampling_rate = sampling_rates[0]
        x_ = x
        y_ = y

    fft_data = np.fft.fft(y_ - np.average(y_))
    freqs = np.fft.fftfreq(len(x_), sampling_rate)

    positive_freqs = freqs[freqs >= 0]
    positive_fft_data = fft_data[freqs >= 0]

    return positive_freqs[np.argmax(np.abs(positive_fft_data))]


def max_height(
    y: np.ndarray,
    percentile: Optional[float] = None,
    absolute: bool = False,
) -> Tuple[float, int]:
    """Get maximum value of y curve and its index.

    Args:
        y: Array of y values.
        percentile: Return that percentile value if provided, otherwise just return max value.
        absolute: Use absolute y value.

    Returns:
        The maximum y value and index.
    """
    if percentile is not None:
        return get_height(y, functools.partial(np.percentile, q=percentile), absolute)
    return get_height(y, np.nanmax, absolute)


def min_height(
    y: np.ndarray,
    percentile: Optional[float] = None,
    absolute: bool = False,
) -> Tuple[float, int]:
    """Get minimum value of y curve and its index.

    Args:
        y: Array of y values.
        percentile: Return that percentile value if provided, otherwise just return min value.
        absolute: Use absolute y value.

    Returns:
        The minimum y value and index.
    """
    if percentile is not None:
        return get_height(y, functools.partial(np.percentile, q=percentile), absolute)
    return get_height(y, np.nanmin, absolute)


def get_height(
    y: np.ndarray,
    find_height: Callable,
    absolute: bool = False,
) -> Tuple[float, int]:
    """Get specific value of y curve defined by a callback and its index.

    Args:
        y: Array of y values.
        find_height: A callback to find preferred y value.
        absolute: Use absolute y value.

    Returns:
        The target y value and index.
    """
    if absolute:
        y_ = np.abs(y)
    else:
        y_ = y

    y_target = find_height(y_)
    index = int(np.argmin(np.abs(y_ - y_target)))

    return y_target, index


def exp_decay(x: np.ndarray, y: np.ndarray) -> float:
    r"""Get exponential decay parameter from monotonically increasing (decreasing) curve.

    This assumes following function form.

    .. math::

        y(x) = e^{\alpha x}

    We can calculate :math:`\alpha` as

    .. math::

        \alpha = \log(y(x)) / x

    To find this number, the numpy polynomial fit with ``deg=1`` is used.

    Args:
        x: Array of x values.
        y: Array of y values.

    Returns:
         Decay rate of signal.
    """
    coeffs = np.polyfit(x, np.log(y), deg=1)

    return float(coeffs[0])


def oscillation_exp_decay(
    x: np.ndarray,
    y: np.ndarray,
    filter_window: int = 5,
    filter_dim: int = 2,
    freq_guess: Optional[float] = None,
) -> float:
    r"""Get exponential decay parameter from oscillating signal.

    This assumes following function form.

    .. math::

        y(x) = e^{\alpha x} F(x),

    where :math:`F(x)` is arbitrary oscillation function oscillating at ``freq_guess``.
    This function first applies a Savitzky-Golay filter to y value,
    then run scipy peak search to extract peak positions.
    If ``freq_guess`` is provided, the search function will be robust to fake peaks due to noise.
    This function calls :py:func:`exp_decay` function for extracted x and y values at peaks.

    .. note::

        y values should contain more than one cycle of oscillation to use this guess approach.

    Args:
        x: Array of x values.
        y: Array of y values.
        filter_window: Window size of Savitzky-Golay filter. This should be odd number.
        filter_dim: Dimension of Savitzky-Golay filter.
        freq_guess: Optional. Initial frequency guess of :math:`F(x)`.

    Returns:
         Decay rate of signal.
    """
    y_smoothed = signal.savgol_filter(y, window_length=filter_window, polyorder=filter_dim)

    if freq_guess is not None and np.abs(freq_guess) > 0:
        period = 1 / np.abs(freq_guess)
        dt = np.mean(np.diff(x))
        width_samples = int(np.round(0.8 * period / dt))
    else:
        width_samples = 1

    peak_pos, _ = signal.find_peaks(y_smoothed, distance=width_samples)

    if len(peak_pos) < 2:
        return 0.0

    x_peaks = x[peak_pos]
    y_peaks = y_smoothed[peak_pos]

    return exp_decay(x_peaks, y_peaks)


def full_width_half_max(
    x: np.ndarray,
    y: np.ndarray,
    peak_index: int,
) -> float:
    """Get full width half maximum value of the peak. Offset of y should be removed.

    Args:
        x: Array of x values.
        y: Array of y values.
        peak_index: Index of peak.

    Returns:
        FWHM of the peak.

    Raises:
        AnalysisError: When peak is too broad and line width is not found.
    """
    y_ = np.abs(y)
    peak_height = y_[peak_index]
    halfmax_removed = np.sign(y_ - 0.5 * peak_height)

    try:
        r_bound = np.min(x[(halfmax_removed == -1) & (x > x[peak_index])])
    except ValueError:
        r_bound = None
    try:
        l_bound = np.max(x[(halfmax_removed == -1) & (x < x[peak_index])])
    except ValueError:
        l_bound = None

    if r_bound and l_bound:
        return r_bound - l_bound
    elif r_bound:
        return 2 * (r_bound - x[peak_index])
    elif l_bound:
        return 2 * (x[peak_index] - l_bound)

    raise AnalysisError("FWHM of input curve was not found. Perhaps scanning range is too narrow.")


def constant_spectral_offset(
    y: np.ndarray, filter_window: int = 5, filter_dim: int = 2, ratio: float = 0.1
) -> float:
    """Get constant offset of spectral baseline.

    This function searches constant offset by finding a region where 1st and 2nd order
    differentiation are close to zero. A return value is an average y value of that region.
    To suppress the noise contribution to derivatives, this function also applies a
    Savitzky-Golay filter to y value.

    This method is more robust to offset error than just taking median or average of y values
    especially when a peak width is wider compared to the scan range.

    Args:
        y: Array of y values.
        filter_window: Window size of Savitzky-Golay filter. This should be odd number.
        filter_dim: Dimension of Savitzky-Golay filter.
        ratio: Threshold value to decide flat region. This value represent a ratio
            to the maximum derivative value.

    Returns:
        Offset value.
    """
    y_smoothed = signal.savgol_filter(y, window_length=filter_window, polyorder=filter_dim)

    ydiff1 = np.abs(np.diff(y_smoothed, 1, append=np.nan))
    ydiff2 = np.abs(np.diff(y_smoothed, 2, append=np.nan, prepend=np.nan))
    non_peaks = y_smoothed[
        (ydiff1 < ratio * np.nanmax(ydiff1)) & (ydiff2 < ratio * np.nanmax(ydiff2))
    ]

    if len(non_peaks) == 0:
        return float(np.median(y))

    return np.average(non_peaks)


def constant_sinusoidal_offset(y: np.ndarray) -> float:
    """Get constant offset of sinusoidal signal.

    This function finds 95 and 5 percentile y values and take an average of them.
    This method is robust to the dependency on sampling window, i.e.
    if we sample sinusoidal signal for 2/3 of its period, simple averaging may induce
    a drift towards positive or negative direction depending on the phase offset.

    Args:
        y: Array of y values.

    Returns:
        Offset value.
    """
    maxv, _ = max_height(y, percentile=95)
    minv, _ = min_height(y, percentile=5)

    return 0.5 * (maxv + minv)