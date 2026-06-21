# Golden HMI Tag Templates

This directory holds golden reference XML templates for HMI Tag import via
TIA Portal Openness (`Hmi.Tag.TagComposition.Import`).

## Why This Directory Exists

The `HmiTagXmlBuilder` class (`backend/backends/classic/tag_xml_builder.py`)
looks here for template files. When a golden template is found, the builder
reads it and replaces placeholders to produce the final XML. When no template
is found, it falls back to generating XML from scratch via code.

## XML Structure

Every HMI Tag XML must follow this structure (note: `Hmi.Tag.Tag`, **not**
`SW.Tag`):

```xml
<?xml version="1.0" encoding="utf-8"?>
<Engineering version="V17" xmlns="http://www.siemens.com/automation/HmiTagML">
  <Hmi.Tag.Tag ID="UNIQUE_ID" CompositionName="Tags">
    <AttributeList>
      <Name>TAG_NAME</Name>
      <DataType>DATA_TYPE</DataType>
      <Address>PLC_ADDRESS</Address>
      <Connection>CONNECTION_NAME</Connection>
      <DefaultTagTable>DefaultTagTable</DefaultTagTable>
      <Comment>COMMENT_TEXT</Comment>
    </AttributeList>
  </Hmi.Tag.Tag>
</Engineering>
```

### Key Rules

1. Root element is `<Engineering>`, **not** `<Document>`.
2. Tag element is `<Hmi.Tag.Tag>`, **not** `<SW.Tag>`.
3. Namespace is `http://www.siemens.com/automation/HmiTagML`.
4. `CompositionName="Tags"` is required for the import target to recognize
   the element.
5. `ID` must be unique per tag element within a single XML file.

## Placeholders

Templates use double-brace placeholders that `HmiTagXmlBuilder` replaces at
generation time:

| Placeholder         | Description                        | Example              |
|---------------------|------------------------------------|----------------------|
| `{{TAG_NAME}}`      | Variable name                      | `Motor_Start`        |
| `{{DATA_TYPE}}`     | Data type                          | `Bool`, `Real`       |
| `{{ADDRESS}}`       | PLC address (empty for internal)   | `%DB1.DBX0.0`        |
| `{{CONNECTION}}`    | Connection name (empty for internal)| `HMI_Connection_1`  |
| `{{COMMENT}}`       | Variable comment                   | `Motor start command`|
| `{{DEFAULT_TAG_TABLE}}` | Tag table name               | `DefaultTagTable`    |

## Template Files

| File                        | Purpose                                      |
|-----------------------------|----------------------------------------------|
| `individual_bool_tag.xml`   | Boolean internal tag (no PLC connection)      |
| `individual_real_tag.xml`   | Real (float) internal tag (no PLC connection) |
| `individual_external_tag.xml` | External tag connected to PLC address       |

## How to Obtain Real Templates

1. Open TIA Portal (V16 or later).
2. Navigate to HMI tag table.
3. Create a single tag with the desired configuration.
4. Right-click the tag table and select **Export**.
5. Open the exported XML and extract the `<Hmi.Tag.Tag>` fragment.
6. Replace concrete values with `{{PLACEHOLDER}}` markers.
7. Save as a new `.xml` file in this directory.

## Relationship to PLC SW.Tag

Do **not** confuse HMI Tag XML with PLC Tag XML:

| Type       | XML Element        | Import Target                       |
|------------|-------------------|-------------------------------------|
| HMI Tag    | `<Hmi.Tag.Tag>`   | `Hmi.Tag.TagComposition.Import`     |
| PLC Tag    | `<SW.Tag>`        | `SW.Blocks.TagComposition.Import`   |

Using `<SW.Tag>` with HMI import will produce the error:
`Class of the 'Siemens.Engineering.SW.Blocks' type ... is not supported`

## Related Files

- `backend/backends/classic/tag_xml_builder.py` -- `HmiTagXmlBuilder` class
- `backend/references/golden_hmi_tag_template.xml` -- legacy golden template
- `backend/references/INSTRUCTIONS_HMI_TAG_XML.md` -- format specification
