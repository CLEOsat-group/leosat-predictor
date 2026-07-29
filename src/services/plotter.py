import matplotlib.pyplot as plt
import os

def generate_plot(pass_times, lat, lon, plot_type='line'):
    print("Pass Times for Plotting:", pass_times)  # Debug print
    plt.figure(figsize=(8, 6))

    if plot_type == 'line':
        plt.plot(range(len(pass_times)), [lat] * len(pass_times), marker='o', label='Satellite Passes')
    elif plot_type == 'scatter':
        plt.scatter(range(len(pass_times)), [lat] * len(pass_times), color='r', label='Satellite Passes')
    elif plot_type == 'bar':
        plt.bar(range(len(pass_times)), [lat] * len(pass_times), label='Satellite Passes')

    plt.xlabel('Prediction Time')
    plt.ylabel('Latitude')
    plt.title(f'Satellite Overpass ({plot_type.title()})')
    plt.legend()

    # Save to root-level static folder
    plot_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../static/plot.png'))
    plt.savefig(plot_path)
    plt.close()

    return plot_path
