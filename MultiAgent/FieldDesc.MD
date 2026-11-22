# PolMaster

{
  "PolicyType": Type of the policy. Some types mean more related tables data
  "PolicyNumber": Unique ID for a policy
  "SystemDate": Registration or start date of the policy
  "EffectiveDate": Effectiveness of the policy,mostly close to System date
  "ExpirationDate": Maturity or benefits expiry date,
  "PolicyStatus": Indicates current state. RPU indicate Reduced Paid Up
  "Language": Communication language , Hindi or one of the southern state lang
  "SumInsured": Total insured sum of the policy across all stakeholders,
  "ThirdParty": Sourced through a vendor
  "JurisdictionState": Indian states std. 2 letter convention. ROI means rest of India
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
      "Additional": Additional roles like Owner(OWN), payor(PAY)
    }
  ],
  "StakerContact": {
    "Address": Any city name
    "mobile": contact number
    "mail": mail id
  },
  "StakerStatus": active, removed. Atleast one active if policy not expired
}