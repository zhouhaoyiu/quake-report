Place official China boundary shapefiles here.

Expected source: 全国地理信息资源目录服务系统 1:100万公众版基础地理信息数据（2021）.
Copy the BOUL*.shp sidecar files into this directory:

- BOUL*.shp
- BOUL*.shx
- BOUL*.dbf
- BOUL*.prj

For another location, set QUAKE_CHINA_BOUNDARY_SHP to the BOUL*.shp path.

Bundled BOUL tiles:

- `*/BOUL_*.shp`
- `*/BOUL_*.shx`
- `*/BOUL_*.dbf`
- `*/BOUL_*.prj`

These files were converted with `ogr2ogr` from 天地图 1:100万公众版基础地理信息数据
downloads. Only the `BOUL` line layer is bundled because the renderer does not
use `BOUA` polygon layers.

Fallback currently bundled:

- `tianditu_china_level2.geojson`
- `tianditu_china_cities.json`

This file is decoded from 天地图服务中心行政区划接口:
`https://cloudcenter.tianditu.gov.cn/api/portal/region/map?gb=156000000&level=2`.
It is used only for China-region maps when BOUL shapefiles are not present.
The city cache stores only names and center coordinates decoded from the same
`region/map` API for local map labels.
