import { useCallback, useState } from 'react'
import { Icon, Modal, Pagination, ResourceState } from './ui'
import { itemsOf, query } from '../lib/api'
import { useDebounce, useResource } from '../lib/hooks'

function PickerDialog({ entity, onChange, onClose }) {
  const [search, setSearch] = useState(''), [page, setPage] = useState(1)
  const q = useDebounce(search)
  const resource = useResource(`/${entity}?${query({ q, page, limit: 8 })}`)
  const rows = itemsOf(resource.data)
  return <Modal title={entity === 'users' ? 'Choose a customer' : 'Choose a restaurant'} onClose={onClose}>
    <label className="search-input picker-search"><input autoFocus aria-label={`Search ${entity} by name`} placeholder="Search by name…" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }}/></label>
    <ResourceState resource={resource} empty={resource.data && !rows.length} emptyTitle="No matches found"/>
    <div className="picker-results">{rows.map((row) => <button key={row.id} onClick={() => { onChange(row.id); onClose() }}><span><b>{row.name}</b><small>{row.id}</small></span></button>)}</div>
    {resource.data && !resource.error && <Pagination page={page} total={resource.data.total} onChange={setPage}/>}
  </Modal>
}

export default function EntityPicker({ entity, selected, onChange, id, label }) {
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  return <><button id={id} type="button" className="entity-picker" aria-label={label || `Choose ${entity === 'users' ? 'customer' : 'restaurant'}`} aria-haspopup="dialog" onClick={() => setOpen(true)}><span>{selected?.name || 'Choose a record'}</span><Icon name="down" size={14}/></button>{open && <PickerDialog entity={entity} onChange={onChange} onClose={close}/>}</>
}

export function RestaurantSelect({ restaurants, value, onChange, id = 'restaurant-select' }) {
  return <EntityPicker entity="restaurants" selected={restaurants.find((restaurant) => restaurant.id === value)} onChange={onChange} id={id}/>
}
