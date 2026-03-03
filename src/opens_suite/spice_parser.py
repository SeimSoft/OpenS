import struct
import os


class SpiceRawParser:
    def __init__(self, filepath):
        self.filepath = filepath
        self.variables = []  # List of (index, name, type)
        self.plots = {}  # plotname -> data dict {var_name: [values]}
        self.no_variables = 0
        self.no_points = 0

    def parse(self):
        if not os.path.exists(self.filepath):
            return None

        self.plots = {}
        with open(self.filepath, "rb") as f:
            while True:
                header = {}
                self.variables = []
                line = ""
                header_finished = False

                # Check for EOF
                first_char = f.read(1)
                if not first_char:
                    break
                f.seek(-1, os.SEEK_CUR)

                while True:
                    char = f.read(1)
                    if not char:
                        header_finished = True
                        break
                    if char == b"\n":
                        decoded_line = line.strip()
                        if decoded_line.startswith("Binary:"):
                            break
                        if decoded_line.startswith("Values:"):
                            break

                        if ":" in decoded_line:
                            parts = decoded_line.split(":", 1)
                            if len(parts) == 2:
                                key, val = parts
                                header[key.strip()] = val.strip()

                        if decoded_line.startswith("Variables:"):
                            no_vars = int(header.get("No. Variables", 0))
                            for i in range(no_vars):
                                v_line = ""
                                while True:
                                    v_char = f.read(1)
                                    if not v_char or v_char == b"\n":
                                        break
                                    v_line += v_char.decode("ascii", errors="ignore")
                                parts = v_line.strip().split()
                                if len(parts) >= 3:
                                    self.variables.append(
                                        (int(parts[0]), parts[1], parts[2])
                                    )
                                elif len(parts) == 2:
                                    self.variables.append(
                                        (int(parts[0]), parts[1], "voltage")
                                    )
                        line = ""
                    else:
                        line += char.decode("ascii", errors="ignore")

                if header_finished and not header:
                    break

                plotname = header.get("Plotname", f"Plot_{len(self.plots)}")
                no_points = int(header.get("No. Points", 0) or 0)
                no_vars = int(header.get("No. Variables", 0) or 0)

                if no_vars == 0:
                    break

                # Read Data
                results = {}
                for _, name, _ in self.variables:
                    results[name] = []

                if not self.variables:
                    break

                is_complex = "complex" in header.get("Flags", "").lower()
                field_size = 16 if is_complex else 8
                fmt = "dd" if is_complex else "d"

                for p in range(no_points):
                    for i in range(no_vars):
                        chunk = f.read(field_size)
                        if not chunk:
                            break
                        val = struct.unpack(fmt, chunk)
                        v_name = self.variables[i][1]
                        if is_complex:
                            results[v_name].append(complex(val[0], val[1]))
                        else:
                            results[v_name].append(val[0])

                self.plots[plotname] = results

                # Skip any trailing newlines
                while True:
                    curr = f.tell()
                    c = f.read(1)
                    if not c:
                        break
                    if c not in (b"\n", b"\r"):
                        f.seek(curr)
                        break

        return self.plots

    @staticmethod
    def find_signal(data, name, type_hint=None):
        """Helper to find a signal in a data dictionary using various naming conventions.
        name: the base name (e.g. 'vin' or 'r1')
        type_hint: 'v' for voltage, 'i' for current
        """
        if not data:
            return None

        # Try exact match first
        if name in data:
            return data[name]

        nl = name.lower()
        # Try case-insensitive exact map
        for k in data.keys():
            if k.lower() == nl:
                return data[k]

        # Try common SPICE/Xyce prefixes
        prefixes = []
        if type_hint == "v":
            prefixes = ["v("]
        elif type_hint == "i":
            prefixes = ["i(", "@"]
        else:
            prefixes = ["v(", "i(", "@"]

        for p in prefixes:
            target = f"{p}{nl})" if p.endswith("(") else f"{p}{nl}"
            for k in data.keys():
                kl = k.lower()
                if (
                    kl == target
                    or kl.startswith(target + "[")
                    or kl.replace("#branch", "") == nl
                ):
                    return data[k]
                if p == "i(" and (kl == f"{nl}:i" or kl == f"i({nl})"):
                    return data[k]

        # Last resort: if name contains :i or resembles a current
        if nl.endswith(":i"):
            base = nl[:-2]
            return SpiceRawParser.find_signal(data, base, "i")

        return None

    def get_op_results(self):
        for name, data in self.plots.items():
            if "Operating Point" in name:
                return {k: v[0] for k, v in data.items() if len(v) > 0}
        if len(self.plots) == 1:
            data = list(self.plots.values())[0]
            return {k: v[0] for k, v in data.items() if len(v) > 0}
        return None
