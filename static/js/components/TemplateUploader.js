/**
 * TemplateUploader 渲染器 — 模板 XML 上传/管理
 *
 * @param {Object} props
 * @param {string} props.templateXml
 * @param {'none'|'uploaded'|'exported'|'default'} props.templateSource
 * @param {string} [props.fileName]
 * @returns {string} HTML string + 绑定事件
 */
export function renderTemplateUploader(props) {
  const { templateXml, templateSource = 'none', fileName = '' } = props;

  const badgeMap = {
    none: '<span class="tmpl-badge tmpl-badge-none">未加载</span>',
    uploaded: '<span class="tmpl-badge tmpl-badge-ok">已上传</span>',
    exported: '<span class="tmpl-badge tmpl-badge-ok">已导出</span>',
    default: '<span class="tmpl-badge tmpl-badge-warn">默认模板</span>',
  };

  const sizeInfo = templateXml
    ? `<span class="tmpl-size">${(new Blob([templateXml]).size / 1024).toFixed(1)} KB</span>`
    : '';

  return `<div class="v4-panel-box">
    <div class="v4-panel-head">模板 XML</div>
    <div class="tmpl-uploader">
      <div class="tmpl-status-line">
        ${badgeMap[templateSource] || badgeMap.none}
        ${fileName ? `<span class="tmpl-fname">${escHtml(fileName)}</span>` : ''}
        ${sizeInfo}
      </div>
      <div class="tmpl-actions">
        <label class="btn tmpl-upload-btn">
          <input type="file" accept=".xml" style="display:none" onchange="
            const file=this.files[0];
            if(!file)return;
            const reader=new FileReader();
            reader.onload=function(e){
              if(window.V4&&window.V4.stores&&window.V4.stores.TmplStore){
                window.V4.stores.TmplStore.setTemplateXml(e.target.result);
                window.V4.stores.TmplStore.setTemplateSource('uploaded');
              }
            };
            reader.readAsText(file);
            this.value='';
          ">上传 XML
        </label>
        ${templateXml ? '<button class="btn" onclick="if(window.V4&&window.V4.stores&&window.V4.stores.TmplStore)window.V4.stores.TmplStore.clearTemplate()">清空</button>' : ''}
      </div>
    </div>
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
}
