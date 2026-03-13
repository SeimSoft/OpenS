"""Programmatic stimuli generation"""

import json
import os
import re
import numpy as np


def _format_scalar(value) -> str:
    """Format a scalar numeric value or a symbolic parameter.

    Accepts values like 1e-6, numpy scalars, or strings like "ENABLE".
    """

    if isinstance(value, str):
        return value
    if isinstance(value, np.generic):
        return str(value.item())
    return str(value)


def _parse_spice_val(value_str: str) -> float:
    """Basic parser for SPICE values: 10k, 10M, 1n..."""
    suffixes = {
        "p": 1e-12,
        "n": 1e-9,
        "u": 1e-6,
        "m": 1e-3,
        "M": 1e-3,  # In Spice, M is milli
        "k": 1e3,
        "Meg": 1e6,
        "meg": 1e6,
        "G": 1e9,
        "T": 1e12,
    }

    value_str = value_str.strip()
    if not value_str:
        return 0.0

    # Sort suffixes by length descending to match 'Meg' before 'm'
    sorted_suffixes = sorted(suffixes.keys(), key=len, reverse=True)
    for s in sorted_suffixes:
        if value_str.endswith(s):
            try:
                num_str = value_str[: -len(s)].strip()
                if not num_str:
                    return 0.0
                return float(num_str) * suffixes[s]
            except ValueError:
                continue

    try:
        return float(value_str)
    except ValueError:
        return 0.0


def _spectre_escape_node(name: str) -> str:
    """Escape a node name for Spectre.

    For bus-like names, Spectre expects angle brackets to be escaped:

        net<0> -> net\<0\>
    """

    s = str(name)
    if s == "0":
        return s

    # Make this idempotent (avoid turning \< into \\<)
    s = s.replace("\\<", "<").replace("\\>", ">")

    if ("<" in s) or (">" in s):
        s = s.replace("<", "\\<").replace(">", "\\>")

    return s


def _spectre_identifier(name: str) -> str:
    # Spectre instance names should be plain identifiers; replace special chars.
    return re.sub(r"[^A-Za-z0-9_]", "_", str(name))


class Stimuli:
    """Stimuli helper class for generating PWL sources and
    component networks for Xyce.
    """

    def __init__(self):
        self._data = {}
        self._t = None
        self._components = {}  # (Node1, Node2) -> Component network
        self._currents = {}  # (n_plus, n_minus) -> expression/scalar

    def __setitem__(self, key, value):
        if key == "t":
            self._t = np.array(value)
            return

        # Bus support: stimuli["name<msb:lsb>"] = [v_lsb, ..., v_msb]
        if isinstance(key, str):
            match = re.fullmatch(
                r"(?P<base>[^<>]+)<(?P<msb>-?\d+):(?P<lsb>-?\d+)>", key
            )
            if match is not None:
                base = match.group("base")
                msb = int(match.group("msb"))
                lsb = int(match.group("lsb"))
                width = abs(msb - lsb) + 1

                if not isinstance(value, (list, tuple, np.ndarray)):
                    raise TypeError(
                        f"Bus assignment for '{key}' must be a list/tuple/array of length {width}."
                    )

                values = list(value)
                if len(values) != width:
                    raise ValueError(
                        f"Bus assignment for '{key}' must have length {width}, got {len(values)}."
                    )

                step = 1 if msb >= lsb else -1
                for offset, v in enumerate(values):
                    idx = lsb + offset * step
                    bit_node = f"{base}<{idx}>"
                    self[bit_node] = v
                return

        # Bus support with explicit reference node:
        #   stimuli["name<msb:lsb>", "REF"] = [v0, ..., vN]
        #   stimuli["REF", "name<msb:lsb>"] = [v0, ..., vN]
        # expands to (name<msb>, REF) / (REF, name<msb>), ...
        if isinstance(key, tuple) and len(key) == 2:
            first, second = key
            _BUS_RE = r"(?P<base>[^<>]+)<(?P<msb>-?\d+):(?P<lsb>-?\d+)>"
            for bus_str, other, bus_first in [
                (first, second, True),
                (second, first, False),
            ]:
                if isinstance(bus_str, str):
                    match = re.fullmatch(_BUS_RE, bus_str)
                    if match is not None:
                        base = match.group("base")
                        msb = int(match.group("msb"))
                        lsb = int(match.group("lsb"))
                        width = abs(msb - lsb) + 1

                        if not isinstance(value, (list, tuple, np.ndarray)):
                            raise TypeError(
                                f"Bus assignment for '{bus_str}' must be a list/tuple/array of length {width}."
                            )
                        values = list(value)
                        if len(values) != width:
                            raise ValueError(
                                f"Bus assignment for '{bus_str}' must have length {width}, got {len(values)}."
                            )

                        step = 1 if msb >= lsb else -1
                        for offset, v in enumerate(values):
                            idx = lsb + offset * step
                            bit_node = f"{base}<{idx}>"
                            self[
                                bit_node if bus_first else other,
                                other if bus_first else bit_node,
                            ] = v
                        return

        # Ensure key is a tuple: (n_in, n_out)
        if isinstance(key, tuple):
            if len(key) != 2:
                raise ValueError(
                    "Key tuple must have exactly two nodes, e.g. ('VOUT', '0')."
                )
            nodes = key
        else:
            nodes = (key, "0")

        # Distinguish component networks from raw stimulus data
        if isinstance(value, BaseElement):
            self._components[nodes] = value
        else:
            self._data[nodes] = value

    def __getitem__(self, key):
        if key == "t":
            return self._t
        if isinstance(key, tuple):
            # Bus readback with explicit reference node:
            #   stimuli["name<msb:lsb>", "REF"] -> [v_msb, ..., v_lsb]
            #   stimuli["REF", "name<msb:lsb>"] -> [v_msb, ..., v_lsb]
            if len(key) == 2:
                first, second = key
                _BUS_RE = r"(?P<base>[^<>]+)<(?P<msb>-?\d+):(?P<lsb>-?\d+)>"
                for bus_str, other, bus_first in [
                    (first, second, True),
                    (second, first, False),
                ]:
                    if isinstance(bus_str, str):
                        match = re.fullmatch(_BUS_RE, bus_str)
                        if match is not None:
                            base = match.group("base")
                            msb = int(match.group("msb"))
                            lsb = int(match.group("lsb"))
                            width = abs(msb - lsb) + 1
                            step = 1 if msb >= lsb else -1
                            return [
                                self._data.get(
                                    (
                                        (
                                            f"{base}<{lsb + offset * step}>"
                                            if bus_first
                                            else other
                                        ),
                                        (
                                            other
                                            if bus_first
                                            else f"{base}<{lsb + offset * step}>"
                                        ),
                                    )
                                )
                                for offset in range(width)
                            ]
            return self._data.get(key)

        # Bus readback support: if the key is a bus notation like
        #   name<msb:lsb>
        # return the list of bit values in LSB->MSB order matching __setitem__.
        if isinstance(key, str):
            match = re.fullmatch(
                r"(?P<base>[^<>]+)<(?P<msb>-?\d+):(?P<lsb>-?\d+)>", key
            )
            if match is not None:
                base = match.group("base")
                msb = int(match.group("msb"))
                lsb = int(match.group("lsb"))
                width = abs(msb - lsb) + 1

                step = 1 if msb >= lsb else -1
                values = []
                for offset in range(width):
                    idx = lsb + offset * step
                    bit_node = f"{base}<{idx}>"
                    # Prefer exact (bit_node, '0') entries (typical for single-node assignments)
                    val = self._data.get((bit_node, "0"))
                    if val is None:
                        # Otherwise search any stored source where the first node matches
                        for (n1, n2), v in self._data.items():
                            if n1 == bit_node:
                                val = v
                                break
                    values.append(val)
                return values

        # For node lookups, return a proxy so users can do:
        #   stimuli["node"] << 1e-6
        #   stimuli["node"] >> 1e-6
        return _NodeRef(self, str(key))

    @staticmethod
    def vdc(dc, ac=None):
        return VdcStimulus(dc, ac=ac)

    @staticmethod
    def vsin(f, amp=1.0, offset=0.0, phase=0.0, ac=None):
        return SinStimulus(f, amp, offset, phase, ac=ac)

    @staticmethod
    def vpulse(v1, v2, td=0, tr=0, tf=0, pw=1, per=2, ac=None):
        return PulseStimulus(v1, v2, td, tr, tf, pw, per, ac=ac)

    @staticmethod
    def vpattern(pattern, vdd=1.0, tr=0.0, tf=0.0, period=1.0, duty=1.0):
        """Create a pattern-based PWL stimulus.

        - `pattern`: iterable of 0/1 (or fractional) values representing the bit pattern
        - `vdd`: amplitude for a '1' value (scales pattern entries)
        - `tr`, `tf`: rise/fall times applied only at code boundaries where the value changes
        - `period`: per-step hold time (time per pattern element)
        - `duty`: accepted for API compatibility; current implementation treats this as 1.0
        """
        return PatternStimulus(
            list(pattern), vdd=vdd, tr=tr, tf=tf, period=period, duty=duty
        )

    @staticmethod
    def res(value):
        return Resistor(value)

    @staticmethod
    def cap(value):
        return Capacitor(value)

    @staticmethod
    def ind(value):
        return Inductor(value)

    def save_json(self, filename, format="spice"):
        if format == "spice":
            runset = self.generate_spice()
        else:
            runset = self.generate_spectre()
        output_data = {"runset": runset}

        with open(filename, "w") as f:
            json.dump(output_data, f, indent=2)

        print(f"Stimuli saved to {filename}")

    def save(self, filename):
        # Backwards-compatible helper: write JSON with a single "runset" key.
        self.save_json(filename, format="spice")

    def save_ascii(self, filename, format="spice"):
        if format == "spice":
            runset = self.generate_spice()
        else:
            runset = self.generate_spectre()

        with open(filename, "w") as f:
            f.write(runset)

        print(f"Stimuli saved to {filename}")

    def _iter_named_sources(self):
        source_counter = 0
        for nodes, value in self._data.items():
            source_counter += 1
            n_in, n_out = nodes
            source_name = (
                f"V_STIM_{source_counter}_{n_in}"
                if n_out == "0"
                else f"V_STIM_{source_counter}_{n_in}_{n_out}"
            )
            yield source_name, n_in, n_out, value

    def _iter_named_currents(self):
        current_counter = 0
        for (n_plus, n_minus), value in self._currents.items():
            current_counter += 1
            # Include node names in the instance name for easier debugging
            name = f"I_STIM_{current_counter}_{n_plus}_TO_{n_minus}"
            yield name, n_plus, n_minus, value

    def generate_spice(self) -> str:
        """Generate a SPICE/Xyce-style netlist string."""

        netlist_lines = []

        # 1) Sources
        for source_name, n_in, n_out, value in self._iter_named_sources():
            dc_str = ""
            ac_str = ""

            if isinstance(value, StimulusExpression):
                if value.dc is not None:
                    dc_str = f" DC {value.dc}"
                if value.ac is not None:
                    ac_str = f" AC {value.ac}"

                native_spice = value.to_spice()
                if native_spice:
                    netlist_lines.append(
                        f"{source_name} {n_in} {n_out}{dc_str}{ac_str} {native_spice}"
                    )
                    continue

                # DC-only sources (including symbolic parameters) should not be
                # evaluated into a PWL even if a time vector is present.
                if isinstance(value, VdcStimulus):
                    netlist_lines.append(
                        f"{source_name} {n_in} {n_out}{dc_str}{ac_str}"
                    )
                    continue

                if self._t is None:
                    netlist_lines.append(
                        f"{source_name} {n_in} {n_out}{dc_str}{ac_str}"
                    )
                    continue

                expr_val = value.evaluate(self._t)
            else:
                expr_val = value

            if np.isscalar(expr_val) or (
                hasattr(expr_val, "size") and np.array(expr_val).size == 1
            ):
                netlist_lines.append(
                    f"{source_name} {n_in} {n_out}{dc_str}{ac_str} {_format_scalar(expr_val)}"
                )
                continue

            if self._t is None:
                netlist_lines.append(f"{source_name} {n_in} {n_out}{dc_str}{ac_str}")
                continue

            eval_array = np.array(expr_val)
            if eval_array.size != self._t.size:
                continue

            pairs = [f"{t} {v}" for t, v in zip(self._t, eval_array)]
            pwl_str = " ".join(pairs)
            netlist_lines.append(
                f"{source_name} {n_in} {n_out}{dc_str}{ac_str} PWL({pwl_str})"
            )

        # 2) Passive networks
        for nodes, network in self._components.items():
            n_in, n_out = nodes
            netlist_lines.append(f"* --- Network between {n_in} and {n_out} ---")
            netlist_lines.extend(network.generate_netlist(n_in, n_out))

        # 3) Current sources
        for name, n_plus, n_minus, value in self._iter_named_currents():
            if isinstance(value, StimulusExpression):
                dc_str = ""
                ac_str = ""
                if value.dc is not None:
                    dc_str = f" DC {value.dc}"
                if value.ac is not None:
                    ac_str = f" AC {value.ac}"

                native = value.to_spice()
                if native:
                    netlist_lines.append(
                        f"{name} {n_plus} {n_minus}{dc_str}{ac_str} {native}"
                    )
                    continue

                if isinstance(value, VdcStimulus):
                    netlist_lines.append(f"{name} {n_plus} {n_minus}{dc_str}{ac_str}")
                    continue

                if self._t is None:
                    # no time vector: just DC/AC if any
                    netlist_lines.append(f"{name} {n_plus} {n_minus}{dc_str}{ac_str}")
                    continue

                expr_val = value.evaluate(self._t)
            else:
                expr_val = value

            if np.isscalar(expr_val) or (
                hasattr(expr_val, "size") and np.array(expr_val).size == 1
            ):
                netlist_lines.append(
                    f"{name} {n_plus} {n_minus} {_format_scalar(expr_val)}"
                )
                continue

            if self._t is None:
                netlist_lines.append(f"{name} {n_plus} {n_minus}")
                continue

            eval_array = np.array(expr_val)
            if eval_array.size != self._t.size:
                continue

            pairs = [f"{t} {v}" for t, v in zip(self._t, eval_array)]
            pwl_str = " ".join(pairs)
            netlist_lines.append(f"{name} {n_plus} {n_minus} PWL({pwl_str})")

        return "\n".join(netlist_lines)

    def generate_spectre(self) -> str:
        """Generate a Spectre-format netlist string.

        Notes:
        - Sources are emitted using `vsource`.
        - Passives are emitted using `resistor`, `capacitor`, `inductor`.
        """

        netlist_lines = ["simulator lang=spectre"]

        # Sources
        for source_name, n_in, n_out, value in self._iter_named_sources():
            inst_name = _spectre_identifier(source_name)
            n_in_s = _spectre_escape_node(n_in)
            n_out_s = _spectre_escape_node(n_out)

            if isinstance(value, StimulusExpression):
                spectre = value.to_spectre(time_vector=self._t)
                if spectre:
                    # spectre string should already contain dc/ac/pwl/sine/pulse specifics
                    netlist_lines.append(
                        f"{inst_name} ({n_in_s} {n_out_s}) vsource {spectre}"
                    )
                    continue

                # Fallback: if only DC is known, emit dc
                if value.dc is not None:
                    netlist_lines.append(
                        f"{inst_name} ({n_in_s} {n_out_s}) vsource type=dc dc={value.dc}"
                    )
                    continue

                netlist_lines.append(f"{inst_name} ({n_in_s} {n_out_s}) vsource")
                continue

            # Numeric (scalar or vector)
            if np.isscalar(value) or (
                hasattr(value, "size") and np.array(value).size == 1
            ):
                netlist_lines.append(
                    f"{inst_name} ({n_in_s} {n_out_s}) vsource type=dc dc={_format_scalar(value)}"
                )
                continue

            if self._t is None:
                netlist_lines.append(f"{inst_name} ({n_in_s} {n_out_s}) vsource")
                continue

            eval_array = np.array(value)
            if eval_array.size != self._t.size:
                netlist_lines.append(f"{inst_name} ({n_in_s} {n_out_s}) vsource")
                continue

            wave_pairs = []
            for t, v in zip(self._t, eval_array):
                wave_pairs.append(f"{t} {v}")
            wave = " ".join(wave_pairs)
            netlist_lines.append(
                f"{inst_name} ({n_in_s} {n_out_s}) vsource type=pwl wave=[{wave}]"
            )

        # Passive networks
        for nodes, network in self._components.items():
            n_in, n_out = nodes
            netlist_lines.append(
                f"// --- Network between {_spectre_escape_node(n_in)} and {_spectre_escape_node(n_out)} ---"
            )
            netlist_lines.extend(network.generate_spectre_netlist(n_in, n_out))

        # Current sources
        for name, n_plus, n_minus, value in self._iter_named_currents():
            inst_name = _spectre_identifier(name)
            n_plus_s = _spectre_escape_node(n_plus)
            n_minus_s = _spectre_escape_node(n_minus)

            if isinstance(value, StimulusExpression):
                spectre_rhs = value.to_spectre(time_vector=self._t)
                if spectre_rhs:
                    netlist_lines.append(
                        f"{inst_name} ({n_plus_s} {n_minus_s}) isource {spectre_rhs}"
                    )
                elif value.dc is not None:
                    netlist_lines.append(
                        f"{inst_name} ({n_plus_s} {n_minus_s}) isource type=dc dc={value.dc}"
                    )
                else:
                    netlist_lines.append(
                        f"{inst_name} ({n_plus_s} {n_minus_s}) isource"
                    )
                continue

            if np.isscalar(value) or (
                hasattr(value, "size") and np.array(value).size == 1
            ):
                netlist_lines.append(
                    f"{inst_name} ({n_plus_s} {n_minus_s}) isource type=dc dc={_format_scalar(value)}"
                )
                continue

            if self._t is None:
                netlist_lines.append(f"{inst_name} ({n_plus_s} {n_minus_s}) isource")
                continue

            eval_array = np.array(value)
            if eval_array.size != self._t.size:
                netlist_lines.append(f"{inst_name} ({n_plus_s} {n_minus_s}) isource")
                continue

            wave_pairs = [f"{t} {v}" for t, v in zip(self._t, eval_array)]
            wave = " ".join(wave_pairs)
            netlist_lines.append(
                f"{inst_name} ({n_plus_s} {n_minus_s}) isource type=pwl wave=[{wave}]"
            )

        return "\n".join(netlist_lines)

    def get_design_variables(self):
        """Return a sorted list of all symbolic parameter names used in the stimuli.

        This collects string-valued entries found in:
        - scalar/list assignments in `_data`
        - current-source entries in `_currents`
        - attributes of StimulusExpression objects (dc, ac, amp, phase, etc.)
        - simple string-valued attributes on component objects
        """

        vars_set = set()

        def _collect(obj):
            if obj is None:
                return
            if isinstance(obj, str):
                vars_set.add(obj)
                return
            # numpy scalar
            if isinstance(obj, np.generic):
                return
            # StimulusExpression: check common attributes which may be symbolic
            if isinstance(obj, StimulusExpression):
                for attr in (
                    "dc",
                    "ac",
                    "f",
                    "amp",
                    "offset",
                    "phase",
                    "v1",
                    "v2",
                ):
                    val = getattr(obj, attr, None)
                    if isinstance(val, str):
                        vars_set.add(val)
                return
            # Iterable containers
            if isinstance(obj, (list, tuple, set)) or hasattr(obj, "tolist"):
                try:
                    for v in list(obj):
                        _collect(v)
                except Exception:
                    pass
                return
            # Generic object: inspect simple attributes for string values
            if hasattr(obj, "__dict__"):
                for v in vars(obj).values():
                    if isinstance(v, str):
                        vars_set.add(v)

        # Scan data entries
        for val in self._data.values():
            _collect(val)

        # Scan current sources
        for val in self._currents.values():
            _collect(val)

        # Scan component parameters
        for comp in self._components.values():
            _collect(comp)

        return sorted(vars_set)


class _NodeRef:
    """Proxy for a node name used to support `<<` and `>>` operators.

    - `stimuli["n"] << value` creates a current source from gnd to n (current into net).
    - `stimuli["n"] >> value` creates a current source from n to gnd (current out of net).
    """

    def __init__(self, stimuli: Stimuli, node: str):
        self._stimuli = stimuli
        self._node = node

    @property
    def value(self):
        return self._stimuli._data.get((self._node, "0"))

    def __getattr__(self, item):
        val = self.value
        if val is None:
            raise AttributeError(item)
        return getattr(val, item)

    def __lshift__(self, value):
        # Current from gnd -> node (into net)
        self._stimuli._currents[("0", self._node)] = value
        return self._stimuli

    def __rshift__(self, value):
        # Current from node -> gnd (out of net)
        self._stimuli._currents[(self._node, "0")] = value
        return self._stimuli


# --- Expression Classes ---


class StimulusExpression:
    def __init__(self, dc=None, ac=None):
        self.dc = dc
        self.ac = ac

    def evaluate(self, t):
        raise NotImplementedError

    def to_spice(self):
        return None

    def to_spectre(self, time_vector=None):
        """Return the RHS of a Spectre `vsource` element.

        Example: `type=sine ampl=1 freq=1k offset=0`
        """
        return None


class VdcStimulus(StimulusExpression):
    def __init__(self, dc, ac=None):
        super().__init__(dc=dc, ac=ac)

    def evaluate(self, t):
        return np.full_like(t, self.dc)

    def to_spice(self):
        # Return empty; DC handled in header usually
        return ""

    def to_spectre(self, time_vector=None):
        parts = [f"type=dc dc={self.dc}"]
        if self.ac is not None:
            parts.append(f"acmag={self.ac}")
        return " ".join(parts)


class SinStimulus(StimulusExpression):
    def __init__(self, f, amp, offset, phase, ac=None):
        super().__init__(dc=offset, ac=ac)
        self.f = f
        self.amp = amp
        self.offset = offset
        self.phase = phase

    def evaluate(self, t):
        return self.offset + self.amp * np.sin(
            2 * np.pi * self.f * t + np.radians(self.phase)
        )

    def to_spice(self):
        # Xyce syntax: SIN(Voffset Vamp FREQ TD THETA PHASE)
        return f"SIN({self.offset} {self.amp} {self.f} 0 0 {self.phase})"

    def to_spectre(self, time_vector=None):
        parts = [
            "type=sine",
            f"ampl={self.amp}",
            f"freq={self.f}",
            f"offset={self.offset}",
            f"phase={self.phase}",
        ]
        if self.ac is not None:
            parts.append(f"acmag={self.ac}")
        return " ".join(parts)


class PulseStimulus(StimulusExpression):
    def __init__(self, v1, v2, td, tr, tf, pw, per, ac=None):
        super().__init__(dc=v1, ac=ac)
        self.v1 = v1
        self.v2 = v2
        self.td = td
        self.tr = tr
        self.tf = tf
        self.pw = pw
        self.per = per

    def evaluate(self, t):
        # Basic periodic pulse implementation for PWL export
        rel_t = (t - self.td) % self.per
        res = np.full_like(t, self.v1, dtype=float)
        mask_v2 = (rel_t >= self.tr) & (rel_t < self.tr + self.pw)
        res[mask_v2] = self.v2
        return res

    def to_spice(self):
        # Xyce syntax: PULSE(V1 V2 TD TR TF PW PER)
        return f"PULSE({self.v1} {self.v2} {self.td} {self.tr} {self.tf} {self.pw} {self.per})"

    def to_spectre(self, time_vector=None):
        parts = [
            "type=pulse",
            f"val0={self.v1}",
            f"val1={self.v2}",
            f"delay={self.td}",
            f"rise={self.tr}",
            f"fall={self.tf}",
            f"width={self.pw}",
            f"period={self.per}",
        ]
        if self.ac is not None:
            parts.append(f"acmag={self.ac}")
        return " ".join(parts)


class PatternStimulus(StimulusExpression):
    def __init__(self, pattern, vdd=1.0, tr=0.0, tf=0.0, period=1.0, duty=1.0):
        super().__init__(dc=None, ac=None)
        self.pattern = list(pattern)
        self.vdd = vdd
        self.tr = tr
        self.tf = tf
        self.period = period
        self.duty = duty

    def evaluate(self, t):
        # produce waveform values for given time vector by repeating pattern
        if t is None:
            return None
        arr = np.array(t)
        res = np.zeros_like(arr, dtype=float)
        n = len(self.pattern)
        if n == 0:
            return res
        # Build PWL points across one full cycle then interpolate
        pts = self._build_points()
        times = np.array([p[0] for p in pts])
        vals = np.array([p[1] for p in pts])
        cycle = float(times[-1]) if len(times) else float(self.period)
        if cycle <= 0:
            return res
        # Map input times into [0, cycle) and use linear interpolation
        tmod = np.mod(arr, cycle)
        return np.interp(tmod, times, vals)

    def to_spice(self):
        pts = self._build_points()
        if not pts:
            return ""
        pwl_pairs = [f"{t} {v}" for t, v in pts]
        pwl_str = " ".join(pwl_pairs)
        return f"PWL({pwl_str})"

    def to_spectre(self, time_vector=None):
        pts = self._build_points()
        if not pts:
            return ""
        parts = [f"{t} {v}" for t, v in pts]
        wave = " ".join(parts)
        return f"type=pwl wave=[{wave}]"

    def _build_points(self):
        """Return ordered list of (time, value) PWL points across one full pattern cycle.

        Semantics:
        - `period` is the per-step *hold* time.
        - For `duty >= 1.0`, each pattern element is held for exactly `period`.
        - A transition to the next pattern value happens only at the boundary between
          steps, over `tr` (0->1) or `tf` (1->0). No extra ramps at the start of steps.

        Example pattern [0, 1, 0] with duty=1, period=P, tr=tf=R produces:
            (0,0), (P,0), (P+R,1), (2P+R,1), (2P+2R,0)
        """

        n = len(self.pattern)
        step = float(self.period)
        if n <= 0 or step <= 0:
            return [(0.0, 0.0), (0.0, 0.0)]

        pts = []

        def push(t, v):
            t = float(t)
            v = float(v)
            if pts and abs(pts[-1][0] - t) < 1e-15:
                pts[-1] = (t, v)
            else:
                pts.append((t, v))

        # Current implementation uses full-step holds and applies tr/tf only at
        # step boundaries when the value changes. `duty` is accepted for API
        # compatibility but is not used.
        t = 0.0

        for i, p in enumerate(self.pattern):
            if isinstance(p, str) and p.startswith("dt="):
                dt_val = _parse_spice_val(p[3:])
                t += dt_val
                if pts:
                    pts[-1] = (t, pts[-1][1])
                continue

            v_curr = float(p) * float(self.vdd)

            # Apply transition if value changed from previous state
            if pts and abs(pts[-1][1] - v_curr) > 1e-9:
                edge = float(self.tr) if v_curr > pts[-1][1] else float(self.tf)
                edge = max(0.0, edge)
                if edge > 0.0:
                    t += edge
                    push(t, v_curr)
                else:
                    push(t, v_curr)

            if not pts:
                push(t, v_curr)
            else:
                push(t, v_curr)

            # Hold value for exactly one step
            t += step
            push(t, v_curr)

        # Ensure the final time is at least the last time point
        final = []
        for t, v in pts:
            t = max(0.0, float(t))
            if final and abs(final[-1][0] - t) < 1e-15:
                final[-1] = (t, v)
            else:
                final.append((t, v))
        return final


def vcount_pattern(
    bits: int,
    num: int = None,
    vdd: float = 1.0,
    tr: float = 0.0,
    tf: float = 0.0,
    period: float = 1.0,
    duty: float = 1.0,
):
    """Generate per-bit PatternStimulus objects for a binary count sequence.

    Returns a list of `PatternStimulus` instances for each bit, ordered LSB -> MSB.

    - `bits`: number of bits
    - `num`: number of count steps (defaults to 2**bits)
    - `vdd`: voltage for logic '1'
    - `tr`, `tf`: rise/fall times
    - `period`: per-step hold time (time per code)
    - `duty`: duty fraction within the step (1.0 means value holds for whole step)
    """
    if num is None:
        num = 1 << bits
    num = int(num)

    # Build count sequence 0..num-1
    seq = list(range(num))

    # For each bit (0 LSB .. bits-1 MSB) create a pattern of 0/1 values over seq
    patterns = []
    for b in range(bits):
        pattern = [((v >> b) & 1) for v in seq]
        ps = PatternStimulus(pattern, vdd=vdd, tr=tr, tf=tf, period=period, duty=duty)
        patterns.append(ps)

    return patterns


# --- Component Classes ---


class BaseElement:
    _id_counter = 0

    def __init__(self):
        BaseElement._id_counter += 1
        self.id = BaseElement._id_counter

    def __add__(self, other):
        return SeriesCombination(self, other)

    def __or__(self, other):
        return ParallelCombination(self, other)

    def generate_netlist(self, n_in, n_out):
        raise NotImplementedError

    def generate_spectre_netlist(self, n_in, n_out):
        raise NotImplementedError


class Resistor(BaseElement):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def generate_netlist(self, n_in, n_out):
        return [f"R_STIM_{self.id} {n_in} {n_out} {self.value}"]

    def generate_spectre_netlist(self, n_in, n_out):
        n_in_s = _spectre_escape_node(n_in)
        n_out_s = _spectre_escape_node(n_out)
        return [f"R_STIM_{self.id} ({n_in_s} {n_out_s}) resistor r={self.value}"]


class Capacitor(BaseElement):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def generate_netlist(self, n_in, n_out):
        return [f"C_STIM_{self.id} {n_in} {n_out} {self.value}"]

    def generate_spectre_netlist(self, n_in, n_out):
        n_in_s = _spectre_escape_node(n_in)
        n_out_s = _spectre_escape_node(n_out)
        return [f"C_STIM_{self.id} ({n_in_s} {n_out_s}) capacitor c={self.value}"]


class Inductor(BaseElement):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def generate_netlist(self, n_in, n_out):
        return [f"L_STIM_{self.id} {n_in} {n_out} {self.value}"]

    def generate_spectre_netlist(self, n_in, n_out):
        n_in_s = _spectre_escape_node(n_in)
        n_out_s = _spectre_escape_node(n_out)
        return [f"L_STIM_{self.id} ({n_in_s} {n_out_s}) inductor l={self.value}"]


class SeriesCombination(BaseElement):
    def __init__(self, e1, e2):
        super().__init__()
        self.e1 = e1
        self.e2 = e2

    def generate_netlist(self, n_in, n_out):
        mid_node = f"N_SERIES_{self.id}"
        return self.e1.generate_netlist(n_in, mid_node) + self.e2.generate_netlist(
            mid_node, n_out
        )

    def generate_spectre_netlist(self, n_in, n_out):
        mid_node = f"N_SERIES_{self.id}"
        return self.e1.generate_spectre_netlist(
            n_in, mid_node
        ) + self.e2.generate_spectre_netlist(mid_node, n_out)


class ParallelCombination(BaseElement):
    def __init__(self, e1, e2):
        super().__init__()
        self.e1 = e1
        self.e2 = e2

    def generate_netlist(self, n_in, n_out):
        # For parallel, attach both elements between the same nodes
        return self.e1.generate_netlist(n_in, n_out) + self.e2.generate_netlist(
            n_in, n_out
        )

    def generate_spectre_netlist(self, n_in, n_out):
        return self.e1.generate_spectre_netlist(
            n_in, n_out
        ) + self.e2.generate_spectre_netlist(n_in, n_out)
