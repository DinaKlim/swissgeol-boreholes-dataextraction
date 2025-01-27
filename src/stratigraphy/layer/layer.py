"""Layer class definition."""

import uuid
from dataclasses import dataclass, field

import fitz
from stratigraphy.depthcolumn.depthcolumnentry import DepthColumnEntry
from stratigraphy.lines.line import TextLine, TextWord
from stratigraphy.text.textblock import MaterialDescription, TextBlock
from stratigraphy.util.interval import AnnotatedInterval, BoundaryInterval


@dataclass
class LayerPrediction:
    """A class to represent predictions for a single layer."""

    material_description: TextBlock | MaterialDescription
    depth_interval: BoundaryInterval | AnnotatedInterval | None
    material_is_correct: bool = None
    depth_interval_is_correct: bool = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def __str__(self) -> str:
        """Converts the object to a string.

        Returns:
            str: The object as a string.
        """
        return (
            f"LayerPrediction(material_description={self.material_description}, depth_interval={self.depth_interval})"
        )

    def to_json(self) -> dict:
        """Converts the object to a dictionary.

        Returns:
            dict: The object as a dictionary.
        """
        return {
            "material_description": self.material_description.to_json() if self.material_description else None,
            "depth_interval": self.depth_interval.to_json() if self.depth_interval else None,
            "material_is_correct": self.material_is_correct,
            "depth_interval_is_correct": self.depth_interval_is_correct,
            "id": str(self.id),
        }

    @staticmethod
    def from_json(json_layer_list: list[dict]) -> list["LayerPrediction"]:
        """Converts a dictionary to an object.

        Args:
            json_layer_list (list[dict]): A list of dictionaries representing the layers.

        Returns:
            list[LayerPrediction]: A list of LayerPrediction objects.
        """
        page_layer_predictions_list: list[LayerPrediction] = []

        # Extract the layer predictions.
        for layer in json_layer_list:
            material_prediction = _create_textblock_object(layer["material_description"]["lines"])
            if "depth_interval" in layer and layer["depth_interval"] is not None:
                depth_interval = layer.get("depth_interval", {})
                start_data = depth_interval.get("start")
                end_data = depth_interval.get("end")
                start = (
                    DepthColumnEntry(
                        value=start_data["value"],
                        rect=fitz.Rect(start_data["rect"]),
                        page_number=start_data["page"],
                    )
                    if start_data is not None
                    else None
                )
                end = (
                    DepthColumnEntry(
                        value=end_data["value"],
                        rect=fitz.Rect(end_data["rect"]),
                        page_number=end_data["page"],
                    )
                    if end_data is not None
                    else None
                )

                depth_interval_prediction = BoundaryInterval(start=start, end=end)
                layer_predictions = LayerPrediction(
                    material_description=material_prediction, depth_interval=depth_interval_prediction
                )
            else:
                layer_predictions = LayerPrediction(material_description=material_prediction, depth_interval=None)

            page_layer_predictions_list.append(layer_predictions)

        return page_layer_predictions_list


def _create_textblock_object(lines: list[dict]) -> TextBlock:
    """Creates a TextBlock object from a dictionary.

    Args:
        lines (list[dict]): A list of dictionaries representing the lines.

    Returns:
        TextBlock: The object.
    """
    text_lines = [TextLine([TextWord(**line)]) for line in lines]
    return TextBlock(text_lines)
