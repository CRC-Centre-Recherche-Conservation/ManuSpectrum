/**
 * Shadow of arches/app/media/js/views/components/widgets/file.js
 * Extended with XY chart rendering in report mode.
 *
 * Diff vs original:
 *   - FileWidgetViewModel -> FileWidgetXYViewModel (from file-widget-xy)
 *   - file.htm -> file-xy.htm (extends file.htm with XY charts)
 *   - Added bindings/plotly import
 *   - Registers ms-file-license, the licence notice/picker used by file-xy.htm
 *     and by the File Viewer card (ms-file-workbench.htm)
 */

import ko from 'knockout';
import FileWidgetXYViewModel from 'viewmodels/file-widget-xy';
import fileWidgetTemplate from 'templates/views/components/widgets/file-xy.htm';
import 'bindings/plotly';
import 'bindings/dropzone';
import 'views/components/ms-file-license';

const viewModel = function (params) {
    params.configKeys = ['acceptedFiles', 'maxFilesize'];
    FileWidgetXYViewModel.apply(this, [params]);
};

export default ko.components.register('file-widget', {
    viewModel: viewModel,
    template: fileWidgetTemplate,
});
