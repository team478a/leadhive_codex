import { useEffect, useState } from 'react'
import { prefectures } from './prefectures'

const municipalityEndpoint = 'https://geolonia.github.io/japanese-addresses/api/ja.json'



type MunicipalityData = Record<string, string[]>
let municipalityRequest: Promise<MunicipalityData> | null = null

function loadMunicipalities() {
  if (!municipalityRequest) {
    municipalityRequest = fetch(municipalityEndpoint).then(response => {
      if (!response.ok) throw new Error('市区町村候補を取得できませんでした。')
      return response.json() as Promise<MunicipalityData>
    }).catch(error => {
      municipalityRequest = null
      throw error
    })
  }
  return municipalityRequest
}

function parseGuidedRegion(value: string) {
  if (value === '全国') return { prefecture: '', municipality: '', guided: true }
  const parts = value.split(/\s*\/\s*/).filter(Boolean)
  const prefecture = parts[0] ?? ''
  const isPrefecture = prefectures.includes(prefecture as typeof prefectures[number])
  const municipality = parts[1] ?? ''
  const isSingleRegion = parts.length <= 2 && !prefectures.includes(municipality as typeof prefectures[number])
  return { prefecture: isPrefecture ? prefecture : '', municipality, guided: isPrefecture && isSingleRegion }
}

export function RegionSelector({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const initial = parseGuidedRegion(value)
  const [manual, setManual] = useState(!initial.guided)
  const [municipalities, setMunicipalities] = useState<MunicipalityData | null>(null)
  const [municipalityError, setMunicipalityError] = useState(false)
  const parsed = parseGuidedRegion(value)

  useEffect(() => {
    let active = true
    loadMunicipalities().then(data => {
      if (active) setMunicipalities(data)
    }).catch(() => {
      if (active) setMunicipalityError(true)
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!parseGuidedRegion(value).guided) setManual(true)
  }, [value])

  if (manual) {
    return <div className="region-selector">
      <label className="field">地域（複数・自由入力）
        <input required maxLength={500} value={value} onChange={event => onChange(event.target.value)}
          placeholder="例：大阪府 / 兵庫県" />
      </label>
      <div className="region-helper"><span>複数地域は「 / 」で区切って入力できます。</span>
        <button type="button" className="guide-link" onClick={() => { setManual(false); onChange('全国') }}>選択式に戻す</button></div>
    </div>
  }

  const cityOptions = parsed.prefecture ? municipalities?.[parsed.prefecture] ?? [] : []
  function setPrefecture(prefecture: string) {
    onChange(prefecture || '全国')
  }
  function setMunicipality(municipality: string) {
    onChange(municipality ? `${parsed.prefecture} / ${municipality}` : parsed.prefecture)
  }

  return <div className="region-selector">
    <div className="region-fields">
      <label className="field">都道府県
        <select value={parsed.prefecture} onChange={event => setPrefecture(event.target.value)}>
          <option value="">全国</option>
          {prefectures.map(prefecture => <option value={prefecture} key={prefecture}>{prefecture}</option>)}
        </select>
      </label>
      <label className="field">市区町村
        {municipalityError ? <input maxLength={200} disabled={!parsed.prefecture} value={parsed.municipality}
          onChange={event => setMunicipality(event.target.value)} placeholder={parsed.prefecture ? '市区町村を入力' : '都道府県を選択'} /> :
          <select disabled={!parsed.prefecture || !municipalities} value={parsed.municipality}
            onChange={event => setMunicipality(event.target.value)}>
            <option value="">{!parsed.prefecture ? '都道府県を選択' : municipalities ? '都道府県全体' : '候補を読み込み中…'}</option>
            {cityOptions.map(city => <option value={city} key={city}>{city}</option>)}
          </select>}
      </label>
    </div>
    <div className="region-helper"><span>選択地域：<strong>{value}</strong></span>
      <button type="button" className="guide-link" onClick={() => setManual(true)}>複数地域・自由入力</button></div>
    {municipalityError && <p className="muted mt-2 text-xs">市区町村候補を取得できないため、手入力へ切り替えました。</p>}
  </div>
}
