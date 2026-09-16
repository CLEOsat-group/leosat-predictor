import json
from flask import Blueprint, request, Response, stream_with_context, current_app

from src.services.results_handler import ResultsHandler

results_bp = Blueprint("results", __name__)
results_handler = ResultsHandler()


@results_bp.route("/get_data", methods=["GET"])
def get_data():
    dataset = request.args.get("dataset", "default_table")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))

    start = (page - 1) * per_page
    return results_handler.get_data(dataset, start, per_page, as_json=True)


@results_bp.route("/get_filtered_results", methods=["POST"])
def get_filtered_results():
    data = request.json
    mode = data.get('mode')
    task_id = data.get('task_id', None)
    filters = data.get('filters', {})

    return results_handler.filter_data(mode=mode,
                                       task_id=task_id,
                                       filters=filters,
                                       as_json=True)


@results_bp.route("/export_data", methods=["GET"])
def export_data():
    dataset = request.args.get("dataset", "prediction_results")
    format = request.args.get("format", "csv")

    result = results_handler.export_data(dataset, format)
    response = Response(result, mimetype="text/csv" if format == "csv" else "application/json")
    response.headers["Content-Disposition"] = f"attachment; filename={dataset}.{format}"
    return response


#
# New: streaming download endpoint used by frontend savePredictionToCSV()
#
@results_bp.route("/download_results/<task_id>", methods=["GET"])
def download_results(task_id):
    """
    Stream the task's normalized prediction_rows as CSV.
    Frontend: window.open(`/api/download_results/${taskId}?format=csv`)
    """
    format = request.args.get("format", "csv")
    if format != "csv":
        return {"error": "only csv format supported for streaming"}, 400

    # generator that yields CSV text
    gen = results_handler.stream_results_csv(task_id)

    filename = f"prediction_{task_id}.csv"
    return Response(stream_with_context(gen()),
                    mimetype="text/csv",
                    headers={
                        "Content-Disposition": f"attachment; filename={filename}"
                    })
