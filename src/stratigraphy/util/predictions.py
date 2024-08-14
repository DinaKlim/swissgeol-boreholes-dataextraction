"""This module contains classes for predictions."""

import logging
import math
import uuid
from dataclasses import dataclass, field

import fitz
import Levenshtein

from stratigraphy.groundwater.groundwater_extraction import GroundwaterInformation
from stratigraphy.util.coordinate_extraction import Coordinate
from stratigraphy.util.depthcolumnentry import DepthColumnEntry
from stratigraphy.util.interval import AnnotatedInterval, BoundaryInterval
from stratigraphy.util.line import TextLine, TextWord
from stratigraphy.util.textblock import MaterialDescription, TextBlock
from stratigraphy.util.util import parse_text

logger = logging.getLogger(__name__)


@dataclass
class BoreholeMetaData:
    """Class to represent metadata of a borehole profile."""

    coordinates: Coordinate | None
    groundwater_information: GroundwaterInformation | None = None


@dataclass
class LayerPrediction:
    """A class to represent predictions for a single layer."""

    material_description: TextBlock | MaterialDescription
    depth_interval: BoundaryInterval | AnnotatedInterval | None
    material_is_correct: bool = None
    depth_interval_is_correct: bool = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


class FilePredictions:
    """A class to represent predictions for a single file."""

    def __init__(
        self,
        layers: list[LayerPrediction],
        file_name: str,
        language: str,
        metadata: BoreholeMetaData = None,
        depths_materials_columns_pairs: list[dict] = None,
        page_sizes: list[dict[str, float]] = None,
    ):
        self.layers: list[LayerPrediction] = layers
        self.depths_materials_columns_pairs: list[dict] = depths_materials_columns_pairs
        self.file_name = file_name
        self.language = language
        self.metadata = metadata
        self.metadata_is_correct: dict = {}
        self.page_sizes: list[dict[str, float]] = page_sizes

    @staticmethod
    def create_from_json(predictions_for_file: dict, file_name: str):
        """Create predictions class for a file given the predictions.json file.

        Args:
            predictions_for_file (dict): The predictions for the file in json format.
            file_name (str): The name of the file.
        """
        page_layer_predictions_list: list[LayerPrediction] = []
        pages_dimensions_list: list[dict[str, float]] = []
        depths_materials_columns_pairs_list: list[dict] = []

        file_language = predictions_for_file["language"]

        metadata = predictions_for_file["metadata"]
        coordinates = None
        if "coordinates" in metadata and metadata["coordinates"] is not None:
            coordinates = Coordinate.from_json(metadata["coordinates"])
        if "groundwater_information" in metadata:
            if metadata["groundwater_information"] is not None:
                groundwater_information = GroundwaterInformation(**metadata["groundwater_information"])
            else:
                groundwater_information = None
        file_metadata = BoreholeMetaData(coordinates=coordinates, groundwater_information=groundwater_information)
        # TODO: Add additional metadata here.

        for layer in predictions_for_file["layers"]:
            material_prediction = _create_textblock_object(layer["material_description"]["lines"])
            if "depth_interval" in layer:
                start = (
                    DepthColumnEntry(
                        value=layer["depth_interval"]["start"]["value"],
                        rect=fitz.Rect(layer["depth_interval"]["start"]["rect"]),
                        page_number=layer["depth_interval"]["start"]["page"],
                    )
                    if layer["depth_interval"]["start"] is not None
                    else None
                )
                end = (
                    DepthColumnEntry(
                        value=layer["depth_interval"]["end"]["value"],
                        rect=fitz.Rect(layer["depth_interval"]["end"]["rect"]),
                        page_number=layer["depth_interval"]["end"]["page"],
                    )
                    if layer["depth_interval"]["end"] is not None
                    else None
                )

                depth_interval_prediction = BoundaryInterval(start=start, end=end)
                layer_predictions = LayerPrediction(
                    material_description=material_prediction, depth_interval=depth_interval_prediction
                )
            else:
                layer_predictions = LayerPrediction(material_description=material_prediction, depth_interval=None)

            page_layer_predictions_list.append(layer_predictions)

        if "depths_materials_column_pairs" in predictions_for_file:
            depths_materials_columns_pairs_list.extend(predictions_for_file["depths_materials_column_pairs"])

        pages_dimensions_list.extend(predictions_for_file["page_dimensions"])

        return FilePredictions(
            layers=page_layer_predictions_list,
            file_name=file_name,
            language=file_language,
            metadata=file_metadata,
            depths_materials_columns_pairs=depths_materials_columns_pairs_list,
            page_sizes=pages_dimensions_list,
        )

    def convert_to_ground_truth(self):
        """Convert the predictions to ground truth format.

        This method is meant to be used in combination with the create_from_label_studio method.
        It converts the predictions to ground truth format, which can then be used for evaluation.

        NOTE: This method should be tested before using it to create new ground truth.

        Returns:
            dict: The predictions in ground truth format.
        """
        ground_truth = {self.file_name: {"metadata": self.metadata}}
        layers = []
        for layer in self.layers:
            material_description = layer.material_description.text
            depth_interval = {
                "start": layer.depth_interval.start.value if layer.depth_interval.start else None,
                "end": layer.depth_interval.end.value if layer.depth_interval.end else None,
            }
            layers.append({"material_description": material_description, "depth_interval": depth_interval})
        ground_truth[self.file_name]["layers"] = layers
        if self.metadata is not None and self.metadata.coordinates is not None:
            ground_truth[self.file_name]["metadata"] = {
                "coordinates": {
                    "E": self.metadata.coordinates.east.coordinate_value,
                    "N": self.metadata.coordinates.north.coordinate_value,
                }
            }
        return ground_truth

    def evaluate(self, ground_truth: dict):
        """Evaluate the predictions against the ground truth.

        Args:
            ground_truth (dict): The ground truth for the file.
        """
        self.evaluate_layers(ground_truth["layers"])
        self.evaluate_metadata(ground_truth.get("metadata"))

    def evaluate_layers(self, ground_truth_layers: list):
        """Evaluate all layers of the predictions against the ground truth.

        Args:
            ground_truth_layers (list): The ground truth layers for the file.
        """
        unmatched_layers = ground_truth_layers.copy()
        for layer in self.layers:
            match, depth_interval_is_correct = self._find_matching_layer(layer, unmatched_layers)
            if match:
                layer.material_is_correct = True
                layer.depth_interval_is_correct = depth_interval_is_correct
            else:
                layer.material_is_correct = False
                layer.depth_interval_is_correct = None

    def evaluate_metadata(self, metadata_ground_truth: dict):
        """Evaluate the metadata of the file against the ground truth.

        Note: For now coordinates is the only metadata extracted and evaluated for.

        Args:
            metadata_ground_truth (dict): The ground truth for the file.
        """
        ############################################################################################################
        ### Compute the metadata correctness for the coordinates.
        ############################################################################################################
        if self.metadata.coordinates is None or (
            metadata_ground_truth is None or metadata_ground_truth.get("coordinates") is None
        ):
            self.metadata_is_correct["coordinates"] = None

        else:
            if (
                self.metadata.coordinates.east.coordinate_value > 2e6
                and metadata_ground_truth["coordinates"]["E"] < 2e6
            ):
                ground_truth_east = int(metadata_ground_truth["coordinates"]["E"]) + 2e6
                ground_truth_north = int(metadata_ground_truth["coordinates"]["N"]) + 1e6
            elif (
                self.metadata.coordinates.east.coordinate_value < 2e6
                and metadata_ground_truth["coordinates"]["E"] > 2e6
            ):
                ground_truth_east = int(metadata_ground_truth["coordinates"]["E"]) - 2e6
                ground_truth_north = int(metadata_ground_truth["coordinates"]["N"]) - 1e6
            else:
                ground_truth_east = int(metadata_ground_truth["coordinates"]["E"])
                ground_truth_north = int(metadata_ground_truth["coordinates"]["N"])

            if (math.isclose(int(self.metadata.coordinates.east.coordinate_value), ground_truth_east, abs_tol=2)) and (
                math.isclose(int(self.metadata.coordinates.north.coordinate_value), ground_truth_north, abs_tol=2)
            ):
                self.metadata_is_correct["coordinates"] = True
            else:
                self.metadata_is_correct["coordinates"] = False

        ############################################################################################################
        ### Compute the metadata correctness for the groundwater information.
        ############################################################################################################
        if self.metadata.groundwater_information is None or (
            metadata_ground_truth is None or metadata_ground_truth.get("groundwater") is None
        ):
            self.metadata_is_correct["groundwater_information"] = None
            self.metadata_is_correct["groundwater_information_depth"] = None
            self.metadata_is_correct["groundwater_information_elevation"] = None
            self.metadata_is_correct["groundwater_information_date"] = None
        else:
            if len(metadata_ground_truth["groundwater"]) > 1:
                # TODO: We could also check if the groundwater information is the same for all entries.
                # TODO: We could also take the most recent entry.
                logger.warning(
                    f"Multiple groundwater information entries found in the ground truth for file {self.file_name}."
                    " Only the first entry will be considered for evaluation."
                )
            extracted_groundwater_info: GroundwaterInformation = self.metadata.groundwater_information
            gt_groundwater_info: GroundwaterInformation = GroundwaterInformation(
                **metadata_ground_truth["groundwater"][0]
            )
            self.metadata_is_correct["groundwater_information"] = gt_groundwater_info.is_extracted_information_correct(
                extracted_groundwater_info
            )
            self.metadata_is_correct["groundwater_information_depth"] = gt_groundwater_info.is_extracted_depth_correct(
                extracted_groundwater_info.depth
            )
            self.metadata_is_correct["groundwater_information_elevation"] = (
                gt_groundwater_info.is_extracted_elevation_correct(extracted_groundwater_info.elevation)
            )
            self.metadata_is_correct["groundwater_information_date"] = gt_groundwater_info.is_extracted_date_correct(
                extracted_groundwater_info.date
            )

    @staticmethod
    def _find_matching_layer(
        layer: LayerPrediction, unmatched_layers: list[dict]
    ) -> tuple[dict, bool] | tuple[None, None]:
        """Find the matching layer in the ground truth.

        Args:
            layer (LayerPrediction): The layer to match.
            unmatched_layers (list[dict]): The layers from the ground truth that were not yet matched during the
                                           current evaluation.

        Returns:
            tuple[dict, bool] | tuple[None, None]: The matching layer and a boolean indicating if the depth interval
                                is correct. None if no match was found.
        """
        parsed_text = parse_text(layer.material_description.text)
        possible_matches = [
            ground_truth_layer
            for ground_truth_layer in unmatched_layers
            if Levenshtein.ratio(parsed_text, ground_truth_layer["material_description"]) > 0.9
        ]

        if not possible_matches:
            return None, None

        for possible_match in possible_matches:
            start = possible_match["depth_interval"]["start"]
            end = possible_match["depth_interval"]["end"]

            if layer.depth_interval is None:
                pass

            elif (
                start == 0 and layer.depth_interval.start is None and end == layer.depth_interval.end.value
            ):  # If not specified differently, we start at 0.
                unmatched_layers.remove(possible_match)
                return possible_match, True

            elif (  # noqa: SIM102
                layer.depth_interval.start is not None and layer.depth_interval.end is not None
            ):  # In all other cases we do not allow a None value.
                if start == layer.depth_interval.start.value and end == layer.depth_interval.end.value:
                    unmatched_layers.remove(possible_match)
                    return possible_match, True

        match = max(possible_matches, key=lambda x: Levenshtein.ratio(parsed_text, x["material_description"]))
        unmatched_layers.remove(match)
        return match, False


def _create_textblock_object(lines: dict) -> TextBlock:
    lines = [TextLine([TextWord(**line)]) for line in lines]
    return TextBlock(lines)
