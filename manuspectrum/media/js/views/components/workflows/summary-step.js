// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import ko from 'knockout';
import FinalStep from 'views/components/workflows/final-step';
import geojsonExtent from 'geojson-extent';
import L from 'leaflet';
import MapComponentViewModel from 'views/components/map';
import selectFeatureLayersFactory from 'views/components/cards/select-feature-layers';
import 'bindings/leaflet';

const viewModel = function(params) {
    FinalStep.apply(this, [params]);
    this.resourceData = ko.observable();
    this.relatedResources = ko.observableArray();

    this.getResourceData = function(resourceid, resourceData) {
        window.fetch(this.urls.api_resources(resourceid) + '?format=json&compact=false&v=beta')
            .then(response => response.json())
            .then(data => resourceData(data));
    };

    this.getRelatedResources = function(resourceid, relatedResources) {
        window.fetch(this.urls.related_resources + resourceid + "?paginate=false")
            .then(response => response.json())
            .then(data => relatedResources(data));
    };

    this.init = function() {
        this.getResourceData(this.resourceid, this.resourceData);
        this.getRelatedResources(this.resourceid, this.relatedResources);
    };

    this.getResourceValue = function(obj, attrs, missingValue = 'none') {
        try {
            return attrs.reduce(function index(obj, i) { return obj[i]; }, obj) || missingValue;
        } catch {
            return missingValue;
        }
    };

    this.prepareMap = function(geojson, source) {
        const mapParams = {};
        if (geojson.features.length > 0) {
            mapParams.bounds = geojsonExtent(geojson);
            mapParams.fitBoundsOptions = { padding: 20 };
        }
        const sourceConfig = {};
        sourceConfig[source] = {
            type: "geojson",
            data: geojson
        };
        mapParams.sources = Object.assign(sourceConfig, mapParams.sources);
        mapParams.layers = selectFeatureLayersFactory(
            '',
            source,
            undefined,
            [],
            true,
            '#ff2222'
        );
        MapComponentViewModel.apply(this, [Object.assign({}, mapParams, {
            activeTab: ko.observable(false),
            zoom: null
        })]);

        this.layers = mapParams.layers;
        this.sources = mapParams.sources;
    };

    this.prepareAnnotation = function(featureCollection) {
        const canvas = featureCollection.features[0].properties.canvas;

        return {
            center: [0, 0],
            crs: L.CRS.Simple,
            zoom: 0,
            afterRender: function(map) {
                L.tileLayer.iiif(canvas + '/info.json').addTo(map);
                const extent = geojsonExtent(featureCollection);
                map.addLayer(L.geoJson(featureCollection, {
                    pointToLayer: function(feature, latlng) {
                        return L.circleMarker(latlng, feature.properties);
                    },
                    style: function(feature) {
                        return feature.properties;
                    }
                }));
                L.control.fullscreen().addTo(map);
                setTimeout(function() {
                    map.fitBounds([
                        [extent[1] - 1, extent[0] - 1],
                        [extent[3] + 1, extent[2] + 1]
                    ]);
                }, 250);
            }
        };
    };

    this.init();
};

export default viewModel;
