import pandas as pd
import matplotlib.pyplot as plt
import sys

filename = sys.argv[1]

# Read the .prn file
df = pd.read_csv(filename, delim_whitespace=True)

# Plot
plt.figure(figsize=(12, 6))
plt.plot(df["TIME"], df["V(VR)"], label="V(VR)", marker="o", markersize=2)
plt.plot(df["TIME"], df["V(VL)"], label="V(VL)", marker="x", markersize=2)
plt.xlabel("Time (s)")
plt.ylabel("Voltage (V)")
plt.title("Inverter PWM Pattern Output")
plt.legend()
plt.grid(True)
plt.savefig("plot.png")
print("Plot saved to plot.png")
