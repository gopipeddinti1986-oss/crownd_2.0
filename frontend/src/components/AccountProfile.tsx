import {useEffect,useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,User} from '../services/api';

type ProfileRecord=Record<string,string|number|boolean|null|undefined>;
type AccountRecord=User&{profile?:ProfileRecord|null;email_verified?:boolean};

export function AccountProfile({user,onUpdate,notify}:{user:User;onUpdate:(updated:User)=>void;notify:(message:string)=>void}){
  const queryClient=useQueryClient();
  const query=useQuery({queryKey:['account-profile',user.id],queryFn:async()=>{const {data}=await api.get('/auth/me');return data as AccountRecord;}});
  const [fields,setFields]=useState<ProfileRecord>({});
  const [busy,setBusy]=useState(false);
  useEffect(()=>{if(query.data)setFields({name:query.data.name,...query.data.profile});},[query.data]);
  function set(field:string,value:string|number|boolean){setFields(current=>({...current,[field]:value}));}
  async function save(event:React.FormEvent){
    event.preventDefault();
    const payload:ProfileRecord={};
    const allowed=user.role==='creator'?['name','username','niche','location','bio','platform','followers','engagement','availability']:user.role==='brand'?['name','industry','website','description']:['name'];
    for(const key of allowed){if(fields[key]!==undefined)payload[key]=fields[key];}
    if('followers'in payload)payload.followers=Number(payload.followers);
    if('engagement'in payload)payload.engagement=Number(payload.engagement);
    setBusy(true);
    try{
      const {data}=await api.put('/me/profile',payload);
      onUpdate({id:data.id,name:data.name,email:data.email,role:data.role});
      await queryClient.invalidateQueries({queryKey:['account-profile',user.id]});
      notify('Profile updated.');
    }catch(error){
      const detail=(error as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
      notify(typeof detail==='string'?detail:'Profile could not be saved. Review the fields and try again.');
    }finally{setBusy(false);}
  }
  if(query.isLoading)return <section className="content-page" role="status">Loading your account profile…</section>;
  if(query.isError)return <section className="content-page"><div className="empty-state" role="alert"><h2>Profile unavailable</h2><p>Your account profile could not be loaded.</p><button className="btn dark-btn" onClick={()=>void query.refetch()}>Retry</button></div></section>;
  return <section className="content-page"><div className="page-heading"><div><div className="eyebrow">ACCOUNT SETTINGS</div><h1>Your profile</h1><p>Update the account details used across your CROWND workspace.</p></div></div>
    <form className="panel profile-form" onSubmit={save}>
      <label>Display name<input required minLength={2} maxLength={120} value={String(fields.name??'')} onChange={event=>set('name',event.target.value)}/></label>
      <label>Email address<input type="email" value={user.email} readOnly/><small>Email changes require a separate verification flow.</small></label>
      {user.role==='creator'&&<>
        <label>Creator username<input required minLength={2} maxLength={60} pattern="[A-Za-z0-9_.-]+" value={String(fields.username??'')} onChange={event=>set('username',event.target.value)}/></label>
        <label>Niche<input required minLength={2} maxLength={80} value={String(fields.niche??'')} onChange={event=>set('niche',event.target.value)}/></label>
        <label>Location<input required minLength={2} maxLength={100} value={String(fields.location??'')} onChange={event=>set('location',event.target.value)}/></label>
        <label>Primary platform<input required minLength={2} maxLength={40} value={String(fields.platform??'')} onChange={event=>set('platform',event.target.value)}/></label>
        <label>Bio<textarea maxLength={5000} value={String(fields.bio??'')} onChange={event=>set('bio',event.target.value)}/></label>
        <label>Followers<input type="number" min="0" max="2000000000" step="1" value={String(fields.followers??0)} onChange={event=>set('followers',event.target.value)}/><small>Creator-reported; not externally verified.</small></label>
        <label>Engagement rate (%)<input type="number" min="0" max="100" step="0.01" value={String(fields.engagement??0)} onChange={event=>set('engagement',event.target.value)}/><small>Creator-reported; not externally verified.</small></label>
        <label className="profile-checkbox"><input type="checkbox" checked={Boolean(fields.availability)} onChange={event=>set('availability',event.target.checked)}/> Available for new partnerships</label>
        <p className="profile-verification">Profile verification: {String(fields.verification??'unverified')}. Audience metrics are not independently verified.</p>
      </>}
      {user.role==='brand'&&<>
        <label>Industry<input required minLength={2} maxLength={80} value={String(fields.industry??'')} onChange={event=>set('industry',event.target.value)}/></label>
        <label>Website<input type="url" pattern="https://.*" maxLength={255} placeholder="https://example.com" value={String(fields.website??'')} onChange={event=>set('website',event.target.value)}/><small>Use a secure HTTPS website URL.</small></label>
        <label>Brand description<textarea maxLength={5000} value={String(fields.description??'')} onChange={event=>set('description',event.target.value)}/></label>
        <p className="profile-verification">Brand verification: {String(fields.verification??'unverified')}.</p>
      </>}
      <button className="btn dark-btn" disabled={busy}>{busy?'Saving profile…':'Save profile'}</button>
    </form>
  </section>;
}
