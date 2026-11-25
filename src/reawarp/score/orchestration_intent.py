"""M20 Score-native orchestration intent module."""
from fractions import Fraction
from dataclasses import dataclass
from typing import Any
from reawarp.score.time import as_fraction
PLAN_FORMAT='eli_lab_reawarp_orchestration_plan'
@dataclass(frozen=True,slots=True)
class PhraseSpan:
 phrase_id:str; start_beats:Any; end_beats:Any; function:str='development'; section_id:str='main'; overlap_group:str|None=None; allow_overlap:bool=False
 def __post_init__(self):
  object.__setattr__(self,'start_beats',as_fraction(self.start_beats));object.__setattr__(self,'end_beats',as_fraction(self.end_beats))
  if not self.phrase_id or self.end_beats<=self.start_beats: raise ValueError('invalid phrase span')
 def to_dict(self):return {'phrase_id':self.phrase_id,'start_beats':str(self.start_beats),'end_beats':str(self.end_beats),'function':self.function,'section_id':self.section_id,'overlap_group':self.overlap_group,'allow_overlap':self.allow_overlap}
 @classmethod
 def from_dict(cls,d):return cls(**d)
@dataclass(frozen=True,slots=True)
class CycleSpec:
 cycle_id:str;role:str;length_beats:Any;phase_beats:Any=Fraction(0);start_beats:Any=Fraction(0);end_beats:Any=None
 def __post_init__(self):
  for n in ('length_beats','phase_beats','start_beats') :object.__setattr__(self,n,as_fraction(getattr(self,n)))
  if self.length_beats<=0:raise ValueError('cycle length must be positive')
  if self.end_beats is not None:object.__setattr__(self,'end_beats',as_fraction(self.end_beats))
 @property
 def normalized_phase(self):return self.phase_beats%self.length_beats
 def onset_beats(self,*,until,from_beat=None):
  stop=as_fraction(until);start=self.start_beats if from_beat is None else as_fraction(from_beat)
  if self.end_beats is not None:stop=min(stop,self.end_beats)
  origin=self.start_beats+self.normalized_phase;k=max(0,(start-origin)//self.length_beats);v=origin+k*self.length_beats
  while v<start:v+=self.length_beats
  out=[]
  while v<stop:out.append(v);v+=self.length_beats
  return tuple(out)
 def to_dict(self):return {'cycle_id':self.cycle_id,'role':self.role,'length_beats':str(self.length_beats),'phase_beats':str(self.phase_beats),'start_beats':str(self.start_beats),'end_beats':None if self.end_beats is None else str(self.end_beats)}
 @classmethod
 def from_dict(cls,d):return cls(**d)
@dataclass(frozen=True,slots=True)
class RoleRelationship:
 relationship_id:str;source_role:str;target_role:str;kind:str;start_beats:Any=Fraction(0);end_beats:Any=None;offset_beats:Any=Fraction(0);response_gap_beats:Any=Fraction(0);transition_intent:str|None=None
 def __post_init__(self):
  for n in ('start_beats','offset_beats','response_gap_beats'):object.__setattr__(self,n,as_fraction(getattr(self,n)))
  if self.end_beats is not None:object.__setattr__(self,'end_beats',as_fraction(self.end_beats))
  if self.source_role==self.target_role or self.kind not in {'unison','reinforcement','doubling','complement','interlock','call_response','antiphonal','counterpoint','convergence'}:raise ValueError('invalid role relationship')
 def target_onsets(self,onsets):
  if self.kind=='convergence' and self.end_beats is None:raise ValueError('convergence requires end_beats')
  out=[]
  for raw in sorted(map(as_fraction,onsets)):
   if self.kind in {'unison','reinforcement','doubling'}:v=raw
   elif self.kind in {'complement','interlock','counterpoint'}:v=raw+self.offset_beats
   elif self.kind in {'call_response','antiphonal'}:v=raw+self.response_gap_beats
   else:
    p=min(Fraction(1),max(Fraction(0),(raw-self.start_beats)/(self.end_beats-self.start_beats)));v=raw+self.offset_beats*(1-p)
   if v>=self.start_beats and (self.end_beats is None or v<self.end_beats):out.append(v)
  return tuple(out)
 def to_dict(self):return {'relationship_id':self.relationship_id,'source_role':self.source_role,'target_role':self.target_role,'kind':self.kind,'start_beats':str(self.start_beats),'end_beats':None if self.end_beats is None else str(self.end_beats),'offset_beats':str(self.offset_beats),'response_gap_beats':str(self.response_gap_beats),'transition_intent':self.transition_intent}
 @classmethod
 def from_dict(cls,d):return cls(**d)
@dataclass(frozen=True,slots=True)
class AttentionSpan:
 role:str;start_beats:Any;end_beats:Any;depth:str;handoff_id:str|None=None;register_low:float|None=None;register_high:float|None=None;spectral_band:str|None=None;reserved_silence:bool=False
 def __post_init__(self):
  object.__setattr__(self,'start_beats',as_fraction(self.start_beats));object.__setattr__(self,'end_beats',as_fraction(self.end_beats))
  if self.depth not in {'foreground','midground','background','absence'} or self.end_beats<=self.start_beats:raise ValueError('invalid attention span')
  if self.depth=='absence':object.__setattr__(self,'reserved_silence',True)
 def to_dict(self):return {'role':self.role,'start_beats':str(self.start_beats),'end_beats':str(self.end_beats),'depth':self.depth,'handoff_id':self.handoff_id,'register_low':self.register_low,'register_high':self.register_high,'spectral_band':self.spectral_band,'reserved_silence':self.reserved_silence}
 @classmethod
 def from_dict(cls,d):return cls(**d)
@dataclass(frozen=True,slots=True)
class MutationPolicy:
 phrase_id:str;stable_anchors:tuple=();preserve_pattern:tuple=();preserve_motif:tuple=();preserve_sound:tuple=();allow_pattern:tuple=();allow_motif:tuple=();allow_sound:tuple=();principal_developments:int=1;deliberate_rupture:bool=False;rupture_reason:str|None=None
 def __post_init__(self):
  if self.principal_developments>1 and (not self.deliberate_rupture or not self.rupture_reason):raise ValueError('multiple principal developments require deliberate rupture and rupture_reason')
 def to_dict(self):return {k:(list(v) if isinstance(v,tuple) else v) for k,v in self.__dict__.items()}
 @classmethod
 def from_dict(cls,d):return cls(**{k:tuple(v) if isinstance(v,list) else v for k,v in d.items()})
@dataclass(frozen=True,slots=True)
class OrchestrationPlan:
 phrases:tuple=();cycles:tuple=();relationships:tuple=();attention:tuple=();mutation_policies:tuple=();seed:int=0;title:str=''
 def __post_init__(self):
  for name in ('phrases','cycles','relationships','attention','mutation_policies'):object.__setattr__(self,name,tuple(getattr(self,name)))
  ids=[p.phrase_id for p in self.phrases]
  if len(ids)!=len(set(ids)):raise ValueError('phrase IDs must be unique')
  for i,a in enumerate(sorted(self.phrases,key=lambda p:p.start_beats)):
   for b in sorted(self.phrases,key=lambda p:p.start_beats)[i+1:]:
    if b.start_beats>=a.end_beats:break
    if not (a.allow_overlap or b.allow_overlap or (a.overlap_group and a.overlap_group==b.overlap_group)):raise ValueError('phrase overlap requires permission')
  if any(m.phrase_id not in ids for m in self.mutation_policies):raise ValueError('mutation policy references unknown phrase')
 @property
 def duration_beats(self):return max([p.end_beats for p in self.phrases]+[a.end_beats for a in self.attention]+[c.end_beats for c in self.cycles if c.end_beats is not None]+[r.end_beats for r in self.relationships if r.end_beats is not None]+[Fraction(0)])
 def attention_at(self,role,beat):
  t=as_fraction(beat);v=[a for a in self.attention if a.role==role and a.start_beats<=t<a.end_beats];return max(v,key=lambda a:a.start_beats) if v else None
 def foreground_at(self,beat):
  t=as_fraction(beat);return tuple(sorted({a.role for a in self.attention if a.depth=='foreground' and a.start_beats<=t<a.end_beats}))
 def to_dict(self):return {'format':PLAN_FORMAT,'schema_version':1,'seed':self.seed,'title':self.title,'phrases':[x.to_dict() for x in self.phrases],'cycles':[x.to_dict() for x in self.cycles],'relationships':[x.to_dict() for x in self.relationships],'attention':[x.to_dict() for x in self.attention],'mutation_policies':[x.to_dict() for x in self.mutation_policies]}
 @classmethod
 def from_dict(cls,d):
  if d.get('format')!=PLAN_FORMAT or int(d.get('schema_version',0))!=1:raise ValueError('unsupported orchestration plan')
  return cls(tuple(PhraseSpan.from_dict(x) for x in d.get('phrases',())),tuple(CycleSpec.from_dict(x) for x in d.get('cycles',())),tuple(RoleRelationship.from_dict(x) for x in d.get('relationships',())),tuple(AttentionSpan.from_dict(x) for x in d.get('attention',())),tuple(MutationPolicy.from_dict(x) for x in d.get('mutation_policies',())),int(d.get('seed',0)),str(d.get('title','')))
def build_orchestration_plan(**kwargs):return OrchestrationPlan(**kwargs)
def inspect_attention_conflicts(plan):
 out=[]
 for i,a in enumerate(plan.attention):
  for b in plan.attention[i+1:]:
   if a.role!=b.role and max(a.start_beats,b.start_beats)<min(a.end_beats,b.end_beats):
    reg=all(v is not None for v in (a.register_low,a.register_high,b.register_low,b.register_high)) and max(a.register_low,b.register_low)<=min(a.register_high,b.register_high)
    spec=a.spectral_band is not None and a.spectral_band==b.spectral_band
    if reg or spec:out.append({'kind':'occupancy_overlap','roles':[a.role,b.role],'heuristic_only':True,'register_overlap':reg,'spectral_overlap':spec})
 return tuple(out)
