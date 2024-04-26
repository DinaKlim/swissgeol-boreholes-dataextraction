"""This module contains functionality for detecting duplicate layers across pdf pages."""

import cv2
import fitz
import numpy as np

from stratigraphy.util.plot_utils import convert_page_to_opencv_img


def remove_duplicate_layers(
    previous_page: fitz.Page, current_page: fitz.Page, layer_predictions: list[dict]
) -> list[dict]:
    """Remove duplicate layers from the current page based on the layers of the previous page.

    We check if a layer on the current page is present on the previous page. This is done by extracting
    an image of the layer and check if that image is present in the previous page by applying template matching.

    The check tests if any given layer is present on the previous page as well. If so, all layers before that layer
    are removed as they are considered duplicates. If we have 3 consecutive layers that are not duplicates, we assume
    that there is no further overlap between the pages and stop the search.

    Args:
        previous_page (fitz.Page): The previous page.
        current_page (fitz.Page): The current page containing the layers.
        layer_predictions (list[dict]): The layers of the current page.

    Returns:
        list[dict]: The layers of the current page without duplicates.
    """
    scale_factor = 3
    current_page_image = convert_page_to_opencv_img(
        current_page, scale_factor=scale_factor, color_mode=cv2.COLOR_BGR2GRAY
    )
    previous_page_image = convert_page_to_opencv_img(
        previous_page, scale_factor=scale_factor, color_mode=cv2.COLOR_BGR2GRAY
    )

    sorted_layers = sorted(layer_predictions, key=lambda x: x["material_description"]["rect"][1])
    duplicated_layer_index = 0
    count_consecutive_non_duplicate_layers = 0
    for layer_index, layer in enumerate(sorted_layers):
        if (
            count_consecutive_non_duplicate_layers >= 3
        ):  # if we have 3 consecutive non-duplicate layers, we can assume that there is no further page overlap
            break
        [x0, y_start, x1, y_end] = layer["material_description"]["rect"]
        x_start = int(scale_factor * min(x0, current_page.rect.width * 0.2))
        x_end = int(scale_factor * min(max(x1, current_page.rect.width * 0.8), previous_page.rect.width - 1))
        y_start = int(scale_factor * max(y_start, 0))  # do not go higher up as otherwise we remove too many layers.
        y_end = int(
            scale_factor * min(y_end + 5, previous_page.rect.height - 5, current_page.rect.height - 5)
        )  # make sure template is smaller than current and previous page
        # get cv2 image of current_page of the bounding_box_coordinates
        layer_image = current_page_image[y_start:y_end, x_start:x_end]
        try:
            img_template_probablility_match = np.max(
                cv2.matchTemplate(previous_page_image, layer_image, cv2.TM_CCOEFF_NORMED)
            )
        except cv2.error:  # there can be strange correlation errors here.
            # Just ignore them as it is only a few over the complete dataset
            img_template_probablility_match = 0
        if (
            img_template_probablility_match > 0.62
        ):  # This number has been tested on the dataset. It is not perfect but works well.
            duplicated_layer_index = layer_index
            count_consecutive_non_duplicate_layers = 0
        else:
            count_consecutive_non_duplicate_layers += 1
    return sorted_layers[duplicated_layer_index:]
