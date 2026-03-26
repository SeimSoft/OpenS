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
                                    if not v_char:
                                        header_finished = True
                                        break
                                    if v_char == b"\n":
                                        break
                                    v_line += v_char.decode("ascii", errors="ignore")
                                if header_finished:
                                    break
                                parts = v_line.strip().split()
                                if len(parts) >= 3:
                                    self.variables.append(
                                        (int(parts[0]), parts[1], parts[2])
                                    )
                                elif len(parts) == 2:
                                    self.variables.append(
                                        (int(parts[0]), parts[1], "voltage")
                                    )
                            if header_finished:
                                break
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

                data_truncated = False
                for p in range(no_points):
                    for i in range(no_vars):
                        chunk = f.read(field_size)
                        if not chunk or len(chunk) < field_size:
                            data_truncated = True
                            break
                        val = struct.unpack(fmt, chunk)
                        v_name = self.variables[i][1]
                        if is_complex:
                            results[v_name].append(complex(val[0], val[1]))
                        else:
                            results[v_name].append(val[0])
                    if data_truncated:
                        break

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
    def find_signal(data, name, type_hint=None, prefix=""):
        """Helper to find a signal in a data dictionary using various naming conventions.
        name: the base name (e.g. 'vin' or 'r1')
        type_hint: 'v' for voltage, 'i' for current
        prefix: hierarchical prefix (e.g. 'X1:X2:')
        """
        if not data:
            return None

        # Apply prefix to name if not GND and not already prefixed
        lookup_name = name
        if prefix and name.lower() not in ("0", "gnd"):
            if "(" in name and name.endswith(")"):
                # e.g. "i(v1)" -> "i(X1:v1)"
                start_p = name.find("(")
                inner = name[start_p + 1 : -1]
                if not inner.lower().startswith(prefix.lower()):
                    lookup_name = name[: start_p + 1] + prefix + inner + ")"
                else:
                    lookup_name = name
            elif not name.lower().startswith(prefix.lower()):
                # e.g. "v1" -> "X1:v1"
                lookup_name = prefix + name
            else:
                lookup_name = name

        # Build list of candidates to try
        candidates = [lookup_name]
        if lookup_name != name:
            # Fallback to the EXACT un-prefixed name (allows subcircuits to find top-level signals)
            candidates.append(name)
            
        # Handle Xyce's weird subcircuit device branch naming (e.g., X_1:V1#branch gets parsed as V:X_1:1#branch)
        if "#branch" in lookup_name:
            import re
            m = re.match(r"(.*:)?([A-Za-z]+)(\d+)#branch$", lookup_name)
            if m:
                hier = m.group(1) or ""
                typ = m.group(2)
                num = m.group(3)
                if hier:
                    xyce_mangled = f"{typ}:{hier}{num}#branch"
                    candidates.append(xyce_mangled)
                    
        for cand in candidates:
            # Try exact match first
            if cand in data:
                return data[cand]

            nl = cand.lower()
            # Try case-insensitive exact map
            for k in data.keys():
                if k.lower() == nl:
                    return data[k]

            # Common SPICE/Xyce signal patterns to try
            search_patterns = []
            if type_hint == "v":
                search_patterns = [f"v({nl})", nl]
            elif type_hint == "i":
                search_patterns = [f"i({nl})", f"{nl}:i", f"{nl}#branch", f"@{nl}[i]"]
            else:
                search_patterns = [f"v({nl})", f"i({nl})", f"{nl}:i", f"{nl}#branch", nl]

            for target in search_patterns:
                for k in data.keys():
                    kl = k.lower()
                    if kl == target or kl.replace("#branch", "") == target or kl.startswith(target + "["):
                        return data[k]
            
            # If still not found, try a very broad search
            for k in data.keys():
                kl = k.lower()
                if nl in kl:
                    # Potential match, e.g. "v(x1:node)" matches "x1:node"
                    if f"({nl})" in kl or kl.endswith(f":{nl}") or kl.endswith(f"({nl})"):
                        return data[k]

        return None

    def get_op_results(self):
        for name, data in self.plots.items():
            if "Operating Point" in name:
                return {k: v[0] for k, v in data.items() if len(v) > 0}
        if len(self.plots) == 1:
            data = list(self.plots.values())[0]
            return {k: v[0] for k, v in data.items() if len(v) > 0}
        return None
