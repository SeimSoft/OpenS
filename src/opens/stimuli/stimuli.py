import json

import os

import re

import numpy as np


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

            return self._data.get(key)

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

                val = float(expr_val)

                netlist_lines.append(
                    f"{source_name} {n_in} {n_out}{dc_str}{ac_str} {val}"
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

                netlist_lines.append(f"{name} {n_plus} {n_minus} {float(expr_val)}")

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
                    f"{inst_name} ({n_in_s} {n_out_s}) vsource type=dc dc={float(value)}"
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
                    f"{inst_name} ({n_plus_s} {n_minus_s}) isource type=dc dc={float(value)}"
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
