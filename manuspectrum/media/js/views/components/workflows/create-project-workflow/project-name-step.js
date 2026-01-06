// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import arches from 'arches';
import uuid from 'uuid';
import ko from 'knockout';
import projectNameStepTemplate from 'templates/views/components/workflows/create-project-workflow/project-name-step.htm';
import 'viewmodels/card';

const NAME_NODEGROUP_ID = 'da931fe7-7020-11ef-8753-0575b5bada34';
const TYPE_NODEGROUP_ID = '67d1c39e-7021-11ef-8753-0575b5bada34';

const viewModel = function(params) {
    const self = this;

    const getProp = (key, prop, isString = false) => {
        if (ko.unwrap(params.value) && params.value()[key]) {
            return prop ? params.value()[key][prop] : params.value()[key];
        }
        return isString ? '' : null;
    };

    const typeTileId = ko.observable(getProp('type', 'tileid'));
    const nameTileId = ko.observable(getProp('name', 'tileid'));

    this.projectResourceId = ko.observable(getProp('projectResourceId'));
    this.typeValue = ko.observable(getProp('type', 'value'));
    this.nameValue = ko.observable(getProp('name', 'value', true));
    this.projectEventTypeRdmCollection = ko.observable('26d7ce44-20e5-44fb-a3c1-dfbe6bdd521b');

    const snapshot = {
        typeValue: self.typeValue(),
        nameValue: self.nameValue(),
    };

    this.updatedValue = ko.pureComputed(() => ({
        projectResourceId: self.projectResourceId(),
        name: { value: self.nameValue(), tileid: nameTileId() },
        type: { value: self.typeValue(), tileid: typeTileId() },
    }));

    this.updatedValue.subscribe((val) => {
        params.value(val);
    });

    this.buildTile = (data, nodeGroupId, resourceid, tileid) => {
        return {
            tileid: tileid || "",
            nodegroup_id: nodeGroupId,
            parenttile_id: null,
            resourceinstance_id: resourceid,
            sortorder: 0,
            tiles: {},
            data: data,
            transaction_id: params.form.workflowId
        };
    };

    this.saveTile = (data, nodeGroupId, resourceid, tileid) => {
        const tile = self.buildTile(data, nodeGroupId, resourceid, tileid);
        return window.fetch(arches.urls.api_tiles(tileid || uuid.generate()), {
            method: 'POST',
            credentials: 'include',
            body: JSON.stringify(tile),
            headers: {
                'Content-Type': 'application/json'
            },
        }).then((response) => {
            if (response.ok) {
                return response.json();
            } else {
                response.json()
                    .then(data => {
                        params.pageVm.alert(
                            new params.form.AlertViewModel('ep-alert-red', data.title, data.message)
                        );
                    })
                    .catch(() => {
                        params.pageVm.alert(
                            new params.form.AlertViewModel('ep-alert-red', params.form.error() || arches.translations.issueSavingWorkflowStep)
                        );
                    });
            }
        });
    };

    params.form.reset = () => {
        self.typeValue(snapshot.typeValue);
        self.nameValue(snapshot.nameValue);
    };

    params.form.save = () => {
        params.form.complete(false);

        const nameTileData = {
            "da931fea-7020-11ef-8753-0575b5bada34": self.nameValue(),
            "da931fe9-7020-11ef-8753-0575b5bada34": null,
            "da931feb-7020-11ef-8753-0575b5bada34": null,
            "da931fec-7020-11ef-8753-0575b5bada34": null
        };

        const typeTileData = {
            "67d1c39e-7021-11ef-8753-0575b5bada34": self.typeValue()
        };

        return self.saveTile(nameTileData, NAME_NODEGROUP_ID, self.projectResourceId(), nameTileId())
            .then((data) => {
                if (data) {
                    nameTileId(data.tileid);
                    self.projectResourceId(data.resourceinstance_id);
                    return self.saveTile(typeTileData, TYPE_NODEGROUP_ID, data.resourceinstance_id, typeTileId());
                } else {
                    params.form.error(arches.translations.issueSavingWorkflowStep);
                }
            })
            .then((data) => {
                if (data) {
                    typeTileId(data.tileid);
                    params.form.savedData(params.form.value());
                    params.form.complete(true);
                    params.form.dirty(false);
                    params.pageVm.alert("");
                } else {
                    params.form.error(arches.translations.issueSavingWorkflowStep);
                }
            });
    };
};

ko.components.register('project-name-step', {
    viewModel: viewModel,
    template: projectNameStepTemplate
});

export default viewModel;
