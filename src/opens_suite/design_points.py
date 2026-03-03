import numpy as np
import re


class CrossProductAccessor:
    def __init__(self, dp):
        self.dp = dp

    def __setitem__(self, key, values):
        self.dp._add_crossproduct(key, values)


class DesignPoints:
    def __init__(self):
        self._data = {}
        self._units = {}
        self._length = 0
        self.crossproduct = CrossProductAccessor(self)

    def _parse_key(self, key):
        # Allow spaces around name and unit
        m = re.match(r"^(.*?)(?:\[(.*?)\])?$", key.strip())
        if m:
            name = m.group(1).strip()
            unit = m.group(2).strip() if m.group(2) else ""
            return name, unit
        return key.strip(), ""

    @staticmethod
    def _parse_val(val):
        if not isinstance(val, str):
            return val

        val = val.strip()
        suffixes = {
            "T": 1e12,
            "G": 1e9,
            "Meg": 1e6,
            "meg": 1e6,
            "k": 1e3,
            "K": 1e3,
            "m": 1e-3,
            "M": 1e-3,  # In Spice, M is milli
            "u": 1e-6,
            "n": 1e-9,
            "p": 1e-12,
            "f": 1e-15,
        }

        # Match number and optional suffix
        m = re.match(
            r"^([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)([TGMkKmunpf]|Meg|meg)?$", val
        )
        if m:
            number = float(m.group(1))
            suffix = m.group(2)
            if suffix:
                return number * suffixes[suffix]
            return number
        return val

    def __setitem__(self, key, value):
        name, unit = self._parse_key(key)

        # Handle list of strings or single string with SI suffix
        if isinstance(value, str):
            value = self._parse_val(value)
        elif isinstance(value, (list, tuple, np.ndarray)):
            value = [self._parse_val(v) for v in value]

        val_array = np.atleast_1d(value)

        if self._length == 0:
            self._length = len(val_array)
        elif self._length == 1 and len(val_array) > 1:
            # Broadcast existing single-row data to the new length
            new_len = len(val_array)
            for k in self._data:
                self._data[k] = np.full(new_len, self._data[k][0])
            self._length = new_len
        elif len(val_array) == 1 and self._length > 1:
            # Broadcast the assigned single value to the existing length
            val_array = np.full(self._length, val_array[0])

        if len(val_array) != self._length:
            raise ValueError(
                f"Length mismatch: assigning array of length {len(val_array)} to DesignPoints of length {self._length}"
            )

        self._data[name] = val_array
        if unit or name not in self._units:
            self._units[name] = unit

    def __getitem__(self, key):
        name, _ = self._parse_key(key)
        if name in self._data:
            return self._data[name]
        raise KeyError(name)

    def _add_crossproduct(self, key, values):
        name, unit = self._parse_key(key)
        values = list(values)

        if self._length == 0:
            self.__setitem__(key, values)
            return

        n_existing = self._length
        n_new = len(values)

        # Duplicate existing columns n_new times
        for k in self._data.keys():
            self._data[k] = np.tile(self._data[k], n_new)

        # Add new column repeated n_existing times for each new value
        new_col = np.repeat(values, n_existing)

        self._length = n_existing * n_new
        self._data[name] = new_col
        if unit or name not in self._units:
            self._units[name] = unit

    @staticmethod
    def _format_si(val):
        if not isinstance(val, (int, float, np.number)):
            return str(val)
        if val == 0:
            return "0"

        abs_val = abs(val)
        prefixes = [
            (1e12, "T"),
            (1e9, "G"),
            (1e6, "Meg"),
            (1e3, "k"),
            (1, ""),
            (1e-3, "m"),
            (1e-6, "u"),
            (1e-9, "n"),
            (1e-12, "p"),
            (1e-15, "f"),
        ]

        for factor, prefix in prefixes:
            if abs_val >= factor * 0.999:  # Small threshold for float rounding
                formatted = f"{val/factor:.4g}"
                # Remove trailing .0 but keep other precision
                if formatted.endswith(".0"):
                    formatted = formatted[:-2]
                return f"{formatted}{prefix}"

        # Fallback for very small or very large numbers
        return f"{val:.3g}"

    def to_ascii(self, n=None):
        if self._length == 0:
            return "Empty DesignPoints"

        keys = list(self._data.keys())
        headers = []
        for k in keys:
            u = self._units.get(k, "")
            headers.append(f"{k} [{u}]" if u else k)

        display_len = self._length
        if n is not None:
            display_len = min(n, self._length)

        # Find column widths
        col_widths = [len(h) for h in headers]
        formatted_data = []

        for i in range(display_len):
            row = []
            for j, k in enumerate(keys):
                val_str = self._format_si(self._data[k][i])
                row.append(val_str)
                col_widths[j] = max(col_widths[j], len(val_str))
            formatted_data.append(row)

        # Build string
        res = []
        header_str = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        res.append(header_str)
        res.append("-" * len(header_str))

        for row in formatted_data:
            res.append(" | ".join(v.ljust(w) for v, w in zip(row, col_widths)))

        if display_len < self._length:
            res.append(f"... and {self._length - display_len} more rows.")

        return "\n".join(res)

    def __repr__(self):
        return self.to_ascii()

    def to_html(self, n=None):
        if self._length == 0:
            return "<i>Empty DesignPoints</i>"

        keys = list(self._data.keys())
        headers = []
        for k in keys:
            u = self._units.get(k, "")
            headers.append(f"{k} [{u}]" if u else k)

        display_len = self._length
        if n is not None:
            display_len = min(n, self._length)

        html = [
            "<table style='border-collapse: collapse; border: 1px solid #ccc; text-align: right;'>"
        ]
        html.append(
            "  <thead style='border-bottom: 2px solid #ccc; background-color: #f8f9fa;'><tr>"
        )
        # Headers
        html.append(
            "    <th style='padding: 8px 12px; border: 1px solid #ccc; font-family: monospace; background-color: #eee;'>#</th>"
        )
        for h in headers:
            html.append(
                f"    <th style='padding: 8px 12px; border: 1px solid #ccc; font-family: monospace;'>{h}</th>"
            )
        html.append("  </tr></thead>")
        html.append("  <tbody>")
        for i in range(display_len):
            bg_color = "#ffffff" if i % 2 == 0 else "#f9f9f9"
            html.append(f"    <tr style='background-color: {bg_color};'>")
            # Index cell
            html.append(
                f"      <td style='padding: 6px 12px; border: 1px solid #ccc; font-family: monospace; background-color: #eee; font-weight: bold;'>{i}</td>"
            )
            for k in keys:
                val_str = self._format_si(self._data[k][i])
                html.append(
                    f"      <td style='padding: 6px 12px; border: 1px solid #ccc; font-family: monospace;'>{val_str}</td>"
                )
            html.append("    </tr>")
        html.append("  </tbody>")
        html.append("</table>")

        if display_len < self._length:
            html.append(
                f"<p>Showing first {display_len} rows of {self._length} rows.</p>"
            )
        else:
            html.append(f"<p>All {self._length} rows shown.</p>")

        return "\n".join(html)

    def _repr_html_(self):
        return self.to_html(n=30)

    @property
    def E24(self):
        """Standard E24 series base values."""
        return np.array(
            [
                1.0,
                1.1,
                1.2,
                1.3,
                1.5,
                1.6,
                1.8,
                2.0,
                2.2,
                2.4,
                2.7,
                3.0,
                3.3,
                3.6,
                3.9,
                4.3,
                4.7,
                5.1,
                5.6,
                6.2,
                6.8,
                7.5,
                8.2,
                9.1,
            ]
        )

    def _generate_series(self, decades):
        """Helper to generate E24 values across multiple decades."""
        base = self.E24
        series = []
        for d in decades:
            series.extend(base * (10**d))
        return np.array(series)

    @property
    def R(self):
        """E24 series Resistors: 1 Ohm to 9.1 MOhm."""
        return self._generate_series(range(0, 7))

    @property
    def L(self):
        """E24 series Inductors: 1 nH to 9.1 H."""
        return self._generate_series(range(-9, 1))

    @property
    def C(self):
        """E24 series Capacitors: 1 pF to 9.1 mF."""
        return self._generate_series(range(-12, -2))

    def _filter_series(self, vals, min_val=None, max_val=None, num=None):
        """Helper to filter and optionally decimate a value series."""
        if min_val is not None:
            vals = vals[vals >= min_val]
        if max_val is not None:
            vals = vals[vals <= max_val]

        if num is not None and len(vals) > num:
            # Use linspace to get 'num' indices uniformly distributed across the available range
            indices = np.linspace(0, len(vals) - 1, num, dtype=int)
            vals = vals[indices]
        return vals

    def get_R(self, min_r=None, max_r=None, num=None):
        """Get E24 resistor values within [min_r, max_r], optionally decimated to 'num' elements."""
        return self._filter_series(self.R, min_r, max_r, num)

    def get_L(self, min_l=None, max_l=None, num=None):
        """Get E24 inductor values within [min_l, max_l], optionally decimated to 'num' elements."""
        return self._filter_series(self.L, min_l, max_l, num)

    def get_C(self, min_c=None, max_c=None, num=None):
        """Get E24 capacitor values within [min_c, max_c], optionally decimated to 'num' elements."""
        return self._filter_series(self.C, min_c, max_c, num)

    def filter(self, mask):
        """Returns a new DesignPoints object containing only the rows where mask is True."""
        mask = np.atleast_1d(mask)
        if mask.dtype != bool:
            mask = mask.astype(bool)

        if len(mask) != self._length:
            raise ValueError(
                f"Mask length {len(mask)} does not match DesignPoints length {self._length}"
            )

        new_dp = DesignPoints()
        new_dp._length = int(np.sum(mask))
        new_dp._units = self._units.copy()
        for k, v in self._data.items():
            new_dp._data[k] = v[mask]
        return new_dp

    def to_dict(self, row_index=0):
        """Returns a dictionary of a specific row in 'Component.Param' format if possible, or just 'Name' keys."""
        if self._length == 0:
            return {}
        if row_index >= self._length:
            raise IndexError("Row index out of range")

        res = {}
        for k in self._data.keys():
            res[k] = self._data[k][row_index]
        return res

    def to_json(self, filepath, row_index=0):
        """Writes a specific row to a JSON file."""
        import json

        data = self.to_dict(row_index)

        # Convert numpy types to native python types for JSON serialization
        serializable = {}
        for k, v in data.items():
            if isinstance(v, (np.generic, np.ndarray)):
                serializable[k] = v.item() if hasattr(v, "item") else v.tolist()
            else:
                serializable[k] = v

        with open(filepath, "w") as f:
            json.dump(serializable, f, indent=4)

    def save(self, filepath, id=0):
        """Alias for to_json to store a specific row (id)."""
        self.to_json(filepath, row_index=id)
