# PolMaster

{
  "PolicyType": Type of the policy,
  "PolicyNumber": Unique ID for a policy
  "SystemDate": Registration or start date of the policy
  "EffectiveDate": Effectiveness of the policy,
  "ExpirationDate": Maturity or benefits expiry date,
  "PolicyStatus": Indicates current state,
  "Language": Communication language , Hindi or one of the southern state lang
  "SumInsured": Total insured sum of the policy across all stakeholders,
  "ThirdParty": Sourced through a vendor
  "JurisdictionState": One of the indian states in std two letter conventio
  "Term": Number of years, followed with suffix 'Y'
  "Frequency": Mode of premium payment
}

## PolStakes
_Link: PolMaster.PolicyNumber = PolStakes.PolNumber_
{
  
  "PolicyNumber": linking field with PolMaster
  "StakerName": Primary Insured or spouse or dependent children based on policy type
  "StakerAge": age of the stakeholder
  "StakerCodes": [
    {
      "Unique": Multiple stakeholders per policy but one stakeholder one unique role
      "Additional": Additional roles like Owner, payor
    }
  ],
  "StakerContact": {
    "Address": Any city name
    "mobile": contact number
    "mail": mail id
  },
  "StakerStatus": active, removed
}