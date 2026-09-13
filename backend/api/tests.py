"""Tests for the parts that used to be broken or unprotected.

Priorities, in order: nobody can read or delete another user's data; a request
cannot make the server download the planet; and results never claim more
precision than they have.
"""

import json
import os
import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from .analysis import vegetation
from .analysis.environment import recommend_crops
from .models import CropType, Field, InvasiveSpeciesReport, SoilAnalysis
from .services import osm_fields, sentinel
from .services.sentinel import SentinelUnavailable
from .services.soilgrids import (
    _available_nitrogen_mg_per_kg,
    _exchangeable_potassium_mg_per_kg,
    estimate_current_moisture,
)
from .validators import BBoxError, choose_zoom, metres_per_pixel, parse_bbox


def device_client(device_id=None):
    client = APIClient()
    client.credentials(HTTP_X_DEVICE_ID=device_id or str(uuid.uuid4()))
    return client


class HealthCheckTests(TestCase):
    def test_health_needs_no_device_and_touches_no_data(self):
        with self.assertNumQueries(0):
            response = APIClient().get(reverse('health'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {'status': 'ok'})


class DeviceAuthenticationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_request_without_device_header_is_rejected(self):
        response = APIClient().get(reverse('field-list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_malformed_device_id_is_rejected(self):
        client = APIClient()
        client.credentials(HTTP_X_DEVICE_ID='not-a-uuid')
        response = client.get(reverse('field-list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_first_request_registers_the_device(self):
        device_id = str(uuid.uuid4())
        response = device_client(device_id).get(reverse('session'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(User.objects.filter(username=f'device_{device_id}').exists())

    def test_same_device_id_maps_to_the_same_user(self):
        device_id = str(uuid.uuid4())
        first = device_client(device_id).get(reverse('session'))
        second = device_client(device_id).get(reverse('session'))

        self.assertEqual(first.data['user_id'], second.data['user_id'])
        self.assertEqual(User.objects.filter(username__startswith='device_').count(), 1)

    def test_device_user_cannot_log_in_with_a_password(self):
        device_id = str(uuid.uuid4())
        device_client(device_id).get(reverse('session'))

        user = User.objects.get(username=f'device_{device_id}')
        self.assertFalse(user.has_usable_password())


class DataIsolationTests(TestCase):
    """The regression that mattered most: cross-tenant reads and deletes."""

    def setUp(self):
        cache.clear()
        self.alice = device_client()
        self.bob = device_client()

        created = self.alice.post(reverse('field-list'), {
            'name': 'Поле Алисы',
            'bounds_json': json.dumps([[41.0, 69.0], [41.1, 69.1]]),
            'center_lat': 41.05,
            'center_lon': 69.05,
            'area_hectares': 12.5,
        }, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.field_id = created.data['id']

    def test_field_is_owned_by_its_creator(self):
        field = Field.objects.get(id=self.field_id)
        self.assertIsNotNone(field.user)
        self.assertTrue(field.user.username.startswith('device_'))

    def test_other_device_does_not_see_the_field(self):
        response = self.bob.get(reverse('field-list'))
        self.assertEqual(response.data['count'], 0)

    def test_other_device_cannot_read_the_field(self):
        response = self.bob.get(reverse('field-detail', args=[self.field_id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_device_cannot_delete_the_field(self):
        response = self.bob.delete(reverse('field-detail', args=[self.field_id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Field.objects.filter(id=self.field_id).exists())

    def test_owner_can_delete_the_field(self):
        response = self.alice.delete(reverse('field-detail', args=[self.field_id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_analysis_cannot_be_saved_into_another_users_field(self):
        with mock.patch('api.views.fertility.analyze_fertility') as analyze:
            analyze.return_value = _fake_fertility_result()
            response = self.bob.post(reverse('analyze'), {
                'bbox': [69.0, 41.0, 69.05, 41.05],
                'field_id': self.field_id,
                'save_result': True,
            }, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(SoilAnalysis.objects.count(), 0)


class CropCatalogueTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = device_client()
        CropType.objects.create(name='Пшеница')

    def test_catalogue_is_readable(self):
        response = self.client.get(reverse('crop-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_catalogue_is_not_writable_over_the_api(self):
        response = self.client.post(reverse('crop-list'), {'name': 'Диверсия'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(CropType.objects.count(), 1)

    def test_catalogue_entries_cannot_be_deleted_over_the_api(self):
        crop = CropType.objects.first()
        response = self.client.delete(reverse('crop-detail', args=[crop.id]))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class BBoxValidationTests(TestCase):
    def test_valid_bbox_is_normalised(self):
        self.assertEqual(
            parse_bbox(['69.0', '41.0', '69.1', '41.1']),
            (69.0, 41.0, 69.1, 41.1),
        )

    def test_wrong_length_is_rejected(self):
        with self.assertRaises(BBoxError):
            parse_bbox([69.0, 41.0, 69.1])

    def test_inverted_bbox_is_rejected(self):
        with self.assertRaises(BBoxError):
            parse_bbox([69.1, 41.0, 69.0, 41.1])

    def test_out_of_range_latitude_is_rejected(self):
        with self.assertRaises(BBoxError):
            parse_bbox([69.0, -95.0, 69.1, 41.0])

    def test_whole_planet_is_rejected(self):
        with self.assertRaises(BBoxError):
            parse_bbox([-180.0, -85.0, 180.0, 85.0])

    def test_non_numeric_input_is_rejected(self):
        with self.assertRaises(BBoxError):
            parse_bbox(['a', 'b', 'c', 'd'])

    def test_endpoint_rejects_a_bad_bbox_before_downloading_anything(self):
        cache.clear()
        with mock.patch('api.views.fertility.analyze_fertility') as analyze:
            response = device_client().post(
                reverse('analyze'), {'bbox': [-180, -85, 180, 85]}, format='json'
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        analyze.assert_not_called()


class TileBudgetTests(TestCase):
    def test_zoom_is_reduced_until_the_area_fits_the_budget(self):
        # ~1 degree square: at zoom 14 that is thousands of tiles.
        bbox = (69.0, 41.0, 70.0, 42.0)
        zoom = choose_zoom(bbox, preferred_zoom=14, max_tiles=64)

        self.assertLess(zoom, 14)

        from .validators import tile_span
        cols, rows = tile_span(bbox, zoom)
        self.assertLessEqual(cols * rows, 64)

    def test_small_area_keeps_the_requested_zoom(self):
        bbox = (69.20, 41.30, 69.21, 41.31)
        self.assertEqual(choose_zoom(bbox, preferred_zoom=14, max_tiles=64), 14)


class GroundResolutionTests(TestCase):
    def test_resolution_matches_the_known_value_at_the_equator(self):
        # Web Mercator zoom 0 is 156543 m/px at the equator.
        self.assertAlmostEqual(metres_per_pixel(0.0, 0), 156543.03, places=1)

    def test_resolution_shrinks_away_from_the_equator(self):
        equator = metres_per_pixel(0.0, 14)
        tashkent = metres_per_pixel(41.3, 14)
        self.assertLess(tashkent, equator)


class SoilDerivationTests(TestCase):
    """The conversions that replaced ``random.uniform``."""

    def test_total_nitrogen_converts_to_available_nitrogen(self):
        # 2 g/kg total N -> 2000 mg/kg -> 2% available = 40 mg/kg
        self.assertEqual(_available_nitrogen_mg_per_kg(2.0), 40.0)

    def test_potassium_is_derived_from_cec(self):
        # 15 cmol(c)/kg * 3% * 391 = 175.95 mg/kg
        self.assertAlmostEqual(_exchangeable_potassium_mg_per_kg(15.0), 176.0, delta=0.5)

    def test_moisture_is_none_when_capacity_is_unknown(self):
        self.assertIsNone(estimate_current_moisture(None, 10.0))

    def test_moisture_rises_with_recent_rainfall(self):
        dry = estimate_current_moisture(40.0, 0.0)
        wet = estimate_current_moisture(40.0, 30.0)
        self.assertLess(dry, wet)
        self.assertLessEqual(wet, 40.0)

    def test_soil_chemistry_is_reproducible_for_the_same_input(self):
        first = estimate_current_moisture(35.0, 12.0)
        second = estimate_current_moisture(35.0, 12.0)
        self.assertEqual(first, second)


class CropRecommendationTests(TestCase):
    def _environment(self, **soil):
        chemistry = {'ph': None, 'nitrogen': None, 'phosphorus': None,
                     'potassium': None, 'moisture': None}
        chemistry.update(soil)
        return {
            'country': 'Узбекистан',
            'weather': {'temp': 22.0},
            'soil_chemistry': chemistry,
        }

    def test_no_recommendations_when_nothing_is_known(self):
        environment = self._environment()
        environment['weather'] = {'temp': None}
        self.assertEqual(recommend_crops(environment), [])

    def test_missing_nitrogen_does_not_disqualify_a_crop(self):
        results = recommend_crops(self._environment(ph=7.0))
        self.assertTrue(results)
        for item in results:
            self.assertLessEqual(item['evaluated_criteria'], 4)

    def test_regional_filter_is_applied(self):
        environment = self._environment(ph=7.0)
        environment['country'] = 'Казахстан'
        names = {item['name'] for item in recommend_crops(environment, limit=50)}
        # Cotton is not in the Kazakhstan list.
        self.assertNotIn('Хлопок', names)


class DashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = device_client()
        self.client.get(reverse('session'))
        self.user = User.objects.get()

        self.field = Field.objects.create(
            user=self.user, name='Поле', bounds_json='[]',
            center_lat=41.0, center_lon=69.0, area_hectares=10.0,
        )
        for index in range(7):
            InvasiveSpeciesReport.objects.create(
                user=self.user, field=self.field, species_name=f'Аномалия {index}',
                location_lat=41.0, location_lon=69.0, status='detected',
            )

    def test_active_report_count_is_not_capped_at_five(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.data['stats']['active_reports'], 7)
        self.assertEqual(len(response.data['active_threats']), 5)

    def test_total_area_is_aggregated(self):
        Field.objects.create(user=self.user, name='Второе', bounds_json='[]',
                             center_lat=41.0, center_lon=69.0, area_hectares=5.25)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.data['stats']['total_area_ha'], 15.25)


class PayloadSizeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = device_client()
        self.client.get(reverse('session'))
        self.user = User.objects.get()
        field = Field.objects.create(user=self.user, name='Поле', bounds_json='[]',
                                     center_lat=41.0, center_lon=69.0)
        self.analysis = SoilAnalysis.objects.create(
            user=self.user, field=field, bbox_json='[]',
            overlay_image='data:image/png;base64,' + 'A' * 5000,
        )

    def test_list_response_omits_the_overlay_image(self):
        response = self.client.get(reverse('soil-analysis-list'))
        item = response.data['results'][0]
        self.assertNotIn('overlay_image', item)
        self.assertTrue(item['has_overlay'])

    def test_detail_response_includes_the_overlay_image(self):
        response = self.client.get(reverse('soil-analysis-detail', args=[self.analysis.id]))
        self.assertIn('overlay_image', response.data)


class AnalysisResponseHonestyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = device_client()

    def test_response_states_how_the_result_was_produced(self):
        with mock.patch('api.views.fertility.analyze_fertility') as analyze, \
             mock.patch('api.views.analyze_environment') as environment:
            analyze.return_value = _fake_fertility_result()
            environment.return_value = {'country': 'Узбекистан', 'crops': []}

            response = self.client.post(reverse('analyze'),
                                        {'bbox': [69.2, 41.3, 69.21, 41.31]}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('method', response.data)
        self.assertIn('imagery', response.data)
        self.assertNotIn('AI Model', response.data['method'])

    def test_upstream_failure_is_reported_not_swallowed(self):
        from .analysis.imagery import AnalysisError

        with mock.patch('api.views.fertility.analyze_fertility',
                        side_effect=AnalysisError('Спутниковые снимки недоступны')):
            response = self.client.post(reverse('analyze'),
                                        {'bbox': [69.2, 41.3, 69.21, 41.31]}, format='json')

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data['error'], 'Спутниковые снимки недоступны')


def _fake_fertility_result():
    return {
        'stats': {
            'very_high': 10.0, 'high': 20.0, 'moderate': 30.0, 'low': 15.0,
            'mountains': 5.0, 'water': 10.0, 'desert': 10.0,
            'analysis_method': 'Эвристика: вегетационный индекс ExG',
        },
        'legend': {},
        'overlay': 'data:image/png;base64,AAAA',
        'bounds': [[41.3, 69.2], [41.31, 69.21]],
        'method': 'Эвристика: вегетационный индекс ExG',
        'imagery': {'zoom': 13, 'metres_per_pixel': 14.3, 'tiles': '4/4'},
    }


class ThrottlingTests(TestCase):
    """The analysis endpoints download tiles and run CV, so they are capped."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_analysis_endpoint_is_rate_limited(self):
        client = device_client()
        payload = {'bbox': [69.2, 41.3, 69.21, 41.31]}

        # ``THROTTLE_RATES`` is read off the throttle class at import time, so
        # override_settings does not reach it -- patch the class attribute.
        rates = {'analysis': '2/hour', 'crud': '100/hour'}

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', rates), \
             mock.patch('api.views.fertility.analyze_fertility') as analyze, \
             mock.patch('api.views.analyze_environment') as environment:
            analyze.return_value = _fake_fertility_result()
            environment.return_value = {'country': 'Узбекистан', 'crops': []}

            statuses = [
                client.post(reverse('analyze'), payload, format='json').status_code
                for _ in range(3)
            ]

        self.assertEqual(statuses[:2], [status.HTTP_200_OK, status.HTTP_200_OK])
        self.assertEqual(statuses[2], status.HTTP_429_TOO_MANY_REQUESTS)

    def test_limit_is_per_device_not_global(self):
        rates = {'analysis': '1/hour', 'crud': '100/hour'}
        payload = {'bbox': [69.2, 41.3, 69.21, 41.31]}

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', rates), \
             mock.patch('api.views.fertility.analyze_fertility') as analyze, \
             mock.patch('api.views.analyze_environment') as environment:
            analyze.return_value = _fake_fertility_result()
            environment.return_value = {'country': 'Узбекистан', 'crops': []}

            alice = device_client().post(reverse('analyze'), payload, format='json')
            bob = device_client().post(reverse('analyze'), payload, format='json')

        self.assertEqual(alice.status_code, status.HTTP_200_OK)
        self.assertEqual(bob.status_code, status.HTTP_200_OK)


class VegetationIndexProfileTests(TestCase):
    """NDVI and ExG are different scales; each needs its own thresholds."""

    def test_ndvi_growth_stages_use_literature_thresholds(self):
        self.assertEqual(vegetation.NDVI.growth_stage(0.05), 'bare_soil')
        self.assertEqual(vegetation.NDVI.growth_stage(0.15), 'emergence')
        self.assertEqual(vegetation.NDVI.growth_stage(0.30), 'vegetative')
        self.assertEqual(vegetation.NDVI.growth_stage(0.50), 'flowering')
        self.assertEqual(vegetation.NDVI.growth_stage(0.70), 'maturation')

    def test_exg_thresholds_are_not_ndvi_thresholds(self):
        # 0.15 is sparse cover in ExG but early growth in NDVI. Sharing the
        # thresholds between the two indices would misreport every scene.
        self.assertEqual(vegetation.EXG.growth_stage(0.15), 'flowering')
        self.assertEqual(vegetation.NDVI.growth_stage(0.15), 'emergence')

    def test_health_score_is_clamped_to_a_percentage(self):
        for profile in (vegetation.NDVI, vegetation.EXG):
            for value in (-5.0, 0.0, 0.5, 5.0):
                score = profile.health_score(value)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)


class SentinelFallbackTests(TestCase):
    """When Sentinel-2 cannot answer, the app degrades instead of failing."""

    def setUp(self):
        cache.clear()

    def test_source_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {'DISABLE_SENTINEL': 'true'}):
            self.assertFalse(sentinel.is_available())

    def test_source_needs_no_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(sentinel.is_available())

    def test_vegetation_falls_back_when_source_is_off(self):
        with mock.patch.object(sentinel, 'is_available', return_value=False), \
             mock.patch('api.analysis.vegetation._from_basemap') as basemap:
            basemap.return_value = {'index_type': 'ExG'}
            result = vegetation.analyze_vegetation((69.2, 41.3, 69.21, 41.31))

        self.assertEqual(result['index_type'], 'ExG')
        basemap.assert_called_once()

    def test_vegetation_falls_back_when_every_scene_is_clouded_out(self):
        with mock.patch.object(sentinel, 'is_available', return_value=True), \
             mock.patch.object(sentinel, 'fetch_ndvi_stats',
                               side_effect=SentinelUnavailable('облачно')), \
             mock.patch('api.analysis.vegetation._from_basemap') as basemap:
            basemap.return_value = {'index_type': 'ExG'}
            result = vegetation.analyze_vegetation((69.2, 41.3, 69.21, 41.31))

        self.assertEqual(result['index_type'], 'ExG')

    def test_vegetation_uses_ndvi_when_a_scene_is_available(self):
        import numpy as np

        ndvi = np.full((8, 8), 0.52, dtype=np.float32)
        stats = {
            'index_mean': 0.52, 'index_min': 0.05, 'index_max': 0.88, 'index_stddev': 0.14,
            'ndvi': ndvi, 'valid': np.ones_like(ndvi, dtype=bool),
            'metadata': {
                'source': 'Sentinel-2 L2A', 'provider': 'Microsoft Planetary Computer',
                'capture_date': '2026-09-05', 'cloud_percent': 0.1,
                'metres_per_pixel': 10, 'valid_coverage': 1.0,
            },
        }
        with mock.patch.object(sentinel, 'is_available', return_value=True), \
             mock.patch.object(sentinel, 'fetch_ndvi_stats', return_value=stats):
            result = vegetation.analyze_vegetation((69.2, 41.3, 69.21, 41.31))

        self.assertEqual(result['index_type'], 'NDVI')
        self.assertEqual(result['growth_stage'], 'flowering')
        self.assertEqual(result['imagery']['capture_date'], '2026-09-05')
        self.assertEqual(result['imagery']['metres_per_pixel'], 10)


class ReflectanceOffsetTests(TestCase):
    """The Sentinel-2 offset that silently skews NDVI if you forget it.

    Since processing baseline 04.00 the products carry BOA_ADD_OFFSET = -1000.
    It cancels in the NDVI numerator but not the denominator, so omitting it
    understates NDVI badly -- measured over one Tashkent field, 0.333 instead
    of 0.494, which is a whole fertility band and one growth stage of error.
    """

    def test_modern_baselines_apply_the_offset(self):
        for baseline in ('04.00', '05.12', '99.99'):
            self.assertIn('-2000', sentinel._ndvi_expression(baseline), baseline)

    def test_legacy_baselines_do_not(self):
        for baseline in ('02.14', '03.01'):
            self.assertNotIn('-2000', sentinel._ndvi_expression(baseline), baseline)

    def test_unknown_baseline_assumes_the_offset(self):
        # Current data is all post-04.00, so this is the safe default.
        self.assertIn('-2000', sentinel._ndvi_expression(None))
        self.assertIn('-2000', sentinel._ndvi_expression('не число'))

    def test_offset_materially_changes_the_result(self):
        # Mean digital numbers from S2C_MSIL2A_20260905T061631 over farmland.
        # (NDVI of the means is not the mean of per-pixel NDVI -- the measured
        # scene means were 0.333 and 0.494 -- but the gap is the same size.)
        red, nir = 2160.0, 4240.0

        without_offset = (nir - red) / (nir + red)
        with_offset = (nir - red) / (nir + red - 2 * sentinel.REFLECTANCE_OFFSET)

        self.assertAlmostEqual(without_offset, 0.325, places=3)
        self.assertAlmostEqual(with_offset, 0.473, places=3)

        # Large enough to move the reading across a fertility band and a
        # growth stage, which is why the offset is not optional.
        self.assertGreater(with_offset - without_offset, 0.14)

        # Concretely: the same field reads as one growth stage earlier.
        self.assertEqual(vegetation.NDVI.growth_stage(without_offset), 'vegetative')
        self.assertEqual(vegetation.NDVI.growth_stage(with_offset), 'flowering')


class CloudMaskingTests(TestCase):
    def test_only_usable_scene_classes_count_as_valid(self):
        # 4 vegetation, 5 bare, 6 water, 7 unclassified, 11 snow are usable;
        # 3 cloud shadow, 8/9 cloud, 10 cirrus, 0 no-data are not.
        self.assertEqual(set(sentinel.VALID_SCL_CLASSES), {4, 5, 6, 7, 11})
        for cloudy in (0, 1, 2, 3, 8, 9, 10):
            self.assertNotIn(cloudy, sentinel.VALID_SCL_CLASSES)


class FertilityBandTests(TestCase):
    """The NDVI bands must not collapse the way the ExG ones once did."""

    def test_every_band_is_reachable(self):
        import numpy as np

        from .analysis.fertility import (
            _NDVI_BANDS,
            L_BARE,
            L_HIGH,
            L_LOW,
            L_MODERATE,
            L_VERY_HIGH,
            _classify_by_vegetation,
        )

        values = np.array([[0.05, 0.20, 0.35, 0.50, 0.70]])
        land = np.ones_like(values, dtype=bool)

        labels = _classify_by_vegetation(values, land, bands=_NDVI_BANDS)

        self.assertEqual(
            list(labels[0]),
            [L_BARE, L_LOW, L_MODERATE, L_HIGH, L_VERY_HIGH],
        )


class OsmFieldTests(TestCase):
    def setUp(self):
        cache.clear()

    def _way(self, ring, landuse='farmland', way_id=1):
        return {
            'type': 'way', 'id': way_id, 'tags': {'landuse': landuse},
            'geometry': [{'lat': lat, 'lon': lon} for lat, lon in ring],
        }

    def test_overpass_geometry_becomes_leaflet_order(self):
        ring = [(41.0, 69.0), (41.0, 69.01), (41.01, 69.01), (41.0, 69.0)]
        feature = osm_fields._element_to_feature(self._way(ring))

        self.assertEqual(feature['bounds'][0], [41.0, 69.0])
        self.assertEqual(feature['type_label'], 'Пашня')

    def test_degenerate_polygons_are_dropped(self):
        self.assertIsNone(osm_fields._element_to_feature(self._way([(41.0, 69.0)])))

    def test_area_is_computed_in_square_metres(self):
        # ~0.01 deg square at 41N: 1113 m tall, 840 m wide -> ~93 ha.
        ring = [(41.0, 69.0), (41.0, 69.01), (41.01, 69.01), (41.01, 69.0), (41.0, 69.0)]
        area = osm_fields._ring_area_sqm(ring)

        self.assertGreater(area, 850_000)
        self.assertLess(area, 1_000_000)

    def test_largest_parcel_comes_first(self):
        small = [(41.0, 69.0), (41.0, 69.001), (41.001, 69.001), (41.0, 69.0)]
        large = [(41.0, 69.0), (41.0, 69.02), (41.02, 69.02), (41.0, 69.0)]

        response = mock.Mock(status_code=200)
        response.json.return_value = {'elements': [
            self._way(small, way_id=1), self._way(large, landuse='orchard', way_id=2),
        ]}

        with mock.patch.object(osm_fields._session, 'post', return_value=response):
            features = osm_fields.lookup_fields(41.0, 69.0)

        self.assertEqual(features[0]['id'], 'way/2')

    def test_unmapped_area_returns_none(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {'elements': []}

        with mock.patch.object(osm_fields._session, 'post', return_value=response):
            self.assertIsNone(osm_fields.lookup_fields(0.0, 0.0))

    def test_radius_is_clamped(self):
        captured = {}
        response = mock.Mock(status_code=200)
        response.json.return_value = {'elements': []}

        def capture(url, data=None, **kwargs):
            captured['query'] = data['data']
            return response

        with mock.patch.object(osm_fields._session, 'post', side_effect=capture):
            osm_fields.lookup_fields(41.0, 69.0, radius=999999)

        self.assertIn(f'around:{osm_fields.MAX_RADIUS_M}', captured['query'])

    def test_upstream_failure_is_not_fatal(self):
        with mock.patch.object(osm_fields._session, 'post', side_effect=OSError('down')):
            self.assertIsNone(osm_fields.lookup_fields(41.0, 69.0))


class FieldDetectionEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = device_client()

    def test_returns_404_when_nothing_is_mapped(self):
        with mock.patch.object(osm_fields, 'lookup_fields', return_value=None):
            response = self.client.post(reverse('field-detect'),
                                        {'lat': 41.05, 'lon': 69.05}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_mapped_boundaries(self):
        features = [{'id': 'way/1', 'type': 'farmland', 'area_hectares': 5.0,
                     'bounds': [[41.0, 69.0]], 'bbox': [69.0, 41.0, 69.1, 41.1]}]
        with mock.patch.object(osm_fields, 'lookup_fields', return_value=features):
            response = self.client.post(reverse('field-detect'),
                                        {'lat': 41.05, 'lon': 69.05}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['features'][0]['id'], 'way/1')
        self.assertEqual(response.data['source'], 'OpenStreetMap')

    def test_rejects_non_numeric_coordinates(self):
        response = self.client.post(reverse('field-detect'),
                                    {'lat': 'север', 'lon': 69.05}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_out_of_range_coordinates(self):
        response = self.client.post(reverse('field-detect'),
                                    {'lat': 120, 'lon': 69.05}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CapabilitiesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = device_client()

    def test_every_source_works_without_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            response = self.client.get(reverse('capabilities'))

        self.assertTrue(response.data['sentinel2_ndvi'])
        self.assertTrue(response.data['field_detection'])

    def test_sources_are_named(self):
        response = self.client.get(reverse('capabilities'))
        self.assertIn('Sentinel-2', response.data['sources']['imagery'])
        self.assertEqual(response.data['sources']['field_boundaries'], 'OpenStreetMap')


class SoilQualityScoreTests(TestCase):
    """The soil half of the fertility index is a documented rule, not a guess."""

    def _properties(self, ph=None, soc=None, cec=None, clay=None, sand=None):
        def entry(value):
            return {'value': value, 'source': 'measured'}
        return {
            'ph': entry(ph), 'organic_carbon': entry(soc), 'cec': entry(cec),
            'clay_percent': entry(clay), 'sand_percent': entry(sand),
            'texture': entry('Суглинок'),
        }

    def test_ideal_loam_scores_one(self):
        from .services.soilgrids import soil_quality_score

        score, factors = soil_quality_score(self._properties(ph=6.8, soc=25, cec=30, clay=20, sand=40))
        self.assertEqual(score, 1.0)
        self.assertEqual(set(factors), {'ph', 'organic_carbon', 'cec', 'texture'})

    def test_missing_factors_are_skipped_not_zeroed(self):
        from .services.soilgrids import soil_quality_score

        score, factors = soil_quality_score(self._properties(ph=6.8))
        self.assertEqual(score, 1.0)
        self.assertEqual(list(factors), ['ph'])

    def test_no_data_yields_none(self):
        from .services.soilgrids import soil_quality_score

        self.assertEqual(soil_quality_score(None), (None, {}))
        self.assertEqual(soil_quality_score(self._properties()), (None, {}))

    def test_acid_and_sandy_soil_scores_low(self):
        from .services.soilgrids import soil_quality_score

        score, _ = soil_quality_score(self._properties(ph=4.8, soc=4, cec=5, clay=5, sand=85))
        self.assertLess(score, 0.35)

    def test_quantiles_become_ranges(self):
        from .services.soilgrids import _extract_layers

        payload = {'properties': {'layers': [{
            'name': 'phh2o', 'unit_measure': {'d_factor': 10},
            'depths': [{'label': '0-5cm', 'values': {'mean': 75, 'Q0.05': 60, 'Q0.95': 86}}],
        }]}}
        layers = _extract_layers(payload)
        self.assertEqual(layers['phh2o'], 7.5)
        self.assertEqual(layers['_ranges']['phh2o'], (6.0, 8.6))


class SeasonalProductivityTests(TestCase):
    def test_season_years_exclude_an_unfinished_season(self):
        from datetime import date

        self.assertEqual(sentinel.season_years(date(2026, 5, 1), years=3), [2025, 2024, 2023])
        self.assertEqual(sentinel.season_years(date(2026, 9, 13), years=3), [2026, 2025, 2024])

    def test_one_scene_per_month_least_cloudy(self):
        scenes = [
            {'id': 'a', 'properties': {'datetime': '2025-06-01T00:00:00Z', 'eo:cloud_cover': 12}},
            {'id': 'b', 'properties': {'datetime': '2025-06-20T00:00:00Z', 'eo:cloud_cover': 3}},
            {'id': 'c', 'properties': {'datetime': '2025-07-02T00:00:00Z', 'eo:cloud_cover': 8}},
        ]
        chosen = {item['id'] for item in sentinel._best_scene_per_month(scenes)}
        self.assertEqual(chosen, {'b', 'c'})

    def test_resolution_reflects_the_bbox_not_the_native_pixel(self):
        # ~3.3 km box at 512 px is ~6.5 m/px -> clamped to the native 10 m.
        self.assertEqual(sentinel.resolution_for((69.20, 41.30, 69.23, 41.33), 512), 10)
        # ~22 km box at 512 px is well above 10 m.
        self.assertGreater(sentinel.resolution_for((69.0, 41.0, 69.2, 41.2), 512), 40)

    def test_cache_packing_round_trips(self):
        import numpy as np

        ndvi = np.random.rand(8, 8).astype(np.float32)
        valid = np.random.rand(8, 8) > 0.5
        out_ndvi, out_valid = sentinel._unpack(sentinel._pack(ndvi, valid))
        self.assertTrue(np.array_equal(ndvi, out_ndvi))
        self.assertTrue(np.array_equal(valid, out_valid))

    def test_composite_score_blends_productivity_and_soil(self):
        import numpy as np

        from .analysis.fertility import _fertility_score

        peak = np.array([[0.75]], dtype=np.float32)
        mean = np.array([[0.50]], dtype=np.float32)

        alone, productivity = _fertility_score(peak, mean, None)
        self.assertAlmostEqual(float(productivity[0, 0]), 1.0, places=5)
        self.assertAlmostEqual(float(alone[0, 0]), 1.0, places=5)

        blended, _ = _fertility_score(peak, mean, 0.0)
        self.assertAlmostEqual(float(blended[0, 0]), 0.65, places=5)


class FertilityFallbackTests(TestCase):
    """Composite -> single scene -> basemap, each labelled."""

    def test_falls_back_to_a_single_scene_when_seasons_are_unavailable(self):
        from .analysis import fertility

        with mock.patch.object(sentinel, 'is_available', return_value=True), \
             mock.patch.object(sentinel, 'fetch_seasonal_productivity',
                               side_effect=SentinelUnavailable('мало снимков')), \
             mock.patch('api.analysis.fertility._from_sentinel') as single:
            single.return_value = {'method': 'одна сцена'}
            result = fertility.analyze_fertility((69.2, 41.3, 69.21, 41.31))

        self.assertEqual(result['method'], 'одна сцена')

    def test_falls_back_to_the_basemap_when_no_scene_exists(self):
        from .analysis import fertility

        with mock.patch.object(sentinel, 'is_available', return_value=True), \
             mock.patch.object(sentinel, 'fetch_seasonal_productivity',
                               side_effect=SentinelUnavailable('нет')), \
             mock.patch.object(sentinel, 'fetch_ndvi_array',
                               side_effect=SentinelUnavailable('нет')), \
             mock.patch('api.analysis.fertility._from_basemap') as basemap:
            basemap.return_value = {'method': 'ExG'}
            result = fertility.analyze_fertility((69.2, 41.3, 69.21, 41.31))

        self.assertEqual(result['method'], 'ExG')

    def test_composite_labels_every_source(self):
        import numpy as np

        from .analysis import fertility
        from .services import worldcover

        size = 16
        season = {
            'peak': np.full((size, size), 0.7, dtype=np.float32),
            'mean': np.full((size, size), 0.45, dtype=np.float32),
            'observations': np.full((size, size), 5, dtype=np.uint16),
            'source': 'Sentinel-2 L2A', 'provider': 'Microsoft Planetary Computer',
            'years': [2026, 2025, 2024], 'scene_dates': ['2025-06-01'], 'scenes_used': 1,
            'metres_per_pixel': 10, 'valid_coverage': 1.0,
        }
        classes = np.full((size, size), worldcover.CROPLAND, dtype=np.uint8)
        classes[:4, :] = worldcover.BUILT_UP
        soil = {'ph': {'value': 6.8}, 'organic_carbon': {'value': 25.0}, 'cec': {'value': 30.0},
                'clay_percent': {'value': 20.0}, 'sand_percent': {'value': 40.0},
                'texture': {'value': 'Суглинок'}, 'provider': 'ISRIC SoilGrids v2.0',
                'resolution_m': 250}

        with mock.patch.object(sentinel, 'is_available', return_value=True), \
             mock.patch.object(sentinel, 'fetch_seasonal_productivity', return_value=season), \
             mock.patch.object(worldcover, 'fetch_landcover',
                               return_value=(classes, {'source': 'ESA WorldCover 2021 v2.0.0'})), \
             mock.patch('api.analysis.fertility.soilgrids.fetch_soil_properties', return_value=soil), \
             mock.patch('api.analysis.fertility.elevation_service.fetch_elevation_grid',
                        return_value=None):
            result = fertility.analyze_fertility((69.2, 41.3, 69.21, 41.31))

        self.assertIn('WorldCover', result['method'])
        self.assertIn('SoilGrids', result['method'])
        self.assertEqual(result['stats']['built_up'], 25.0)
        self.assertEqual(result['stats']['very_high'], 75.0)
        self.assertEqual(result['components']['soil']['score'], 1.0)
        self.assertEqual(result['components']['productivity']['weight'], 0.65)


class LandCoverTests(TestCase):
    def test_class_percentages_ignore_nodata(self):
        import numpy as np

        from .services import worldcover

        classes = np.array([[0, 40], [40, 50]], dtype=np.uint8)
        shares = worldcover.class_percentages(classes)
        self.assertEqual(shares, {40: 50.0, 50: 25.0})

    def test_legend_uses_official_labels(self):
        from .services import worldcover

        legend = worldcover.legend([worldcover.CROPLAND, worldcover.WATER])
        self.assertEqual(set(legend), {'Пашня', 'Вода'})


class BuildingsServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_large_area_is_not_requested(self):
        from .services import buildings

        with mock.patch.object(buildings._session, 'post') as post:
            self.assertIsNone(buildings.lookup_buildings((69.0, 41.0, 69.2, 41.2)))
        post.assert_not_called()

    def test_footprints_get_areas_and_centroids(self):
        from .services import buildings

        response = mock.Mock(status_code=200)
        response.json.return_value = {'elements': [{
            'type': 'way', 'id': 7, 'tags': {'building': 'house', 'building:levels': '2'},
            'geometry': [{'lat': 41.0, 'lon': 69.0}, {'lat': 41.0, 'lon': 69.0002},
                         {'lat': 41.0002, 'lon': 69.0002}, {'lat': 41.0002, 'lon': 69.0}],
        }]}
        with mock.patch.object(buildings._session, 'post', return_value=response):
            features = buildings.lookup_buildings((68.99, 40.99, 69.01, 41.01))

        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]['levels'], 2)
        self.assertGreater(features[0]['area_sqm'], 300)
        self.assertAlmostEqual(features[0]['lat'], 41.0001, places=4)


class CrossTenantWriteTests(TestCase):
    """Records that hang off a field must not be attachable to someone else's."""

    def setUp(self):
        cache.clear()
        self.alice = device_client()
        self.bob = device_client()
        created = self.alice.post(reverse('field-list'), {
            'name': 'Поле Алисы', 'bounds_json': '[]', 'center_lat': 41.0, 'center_lon': 69.0,
        }, format='json')
        self.field_id = created.data['id']

    def test_growth_record_cannot_target_another_users_field(self):
        response = self.bob.post(reverse('growth-list'), {
            'field': self.field_id, 'observation_date': '2026-09-13', 'ndvi_mean': 0.5,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weed_report_cannot_target_another_users_field(self):
        response = self.bob.post(reverse('invasive-list'), {
            'field': self.field_id, 'species_name': 'x', 'location_lat': 41, 'location_lon': 69,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_still_write(self):
        response = self.alice.post(reverse('growth-list'), {
            'field': self.field_id, 'observation_date': '2026-09-13', 'ndvi_mean': 0.5,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_field_detect_rejects_a_non_numeric_radius(self):
        response = self.bob.post(reverse('field-detect'),
                                 {'lat': 41.0, 'lon': 69.0, 'radius_m': 'abc'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
