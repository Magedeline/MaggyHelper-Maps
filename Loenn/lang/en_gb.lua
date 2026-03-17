-- Loenn language file for MaggyHelper entities and triggers

return {
    -- Entity names
    entities = {
        ["MaggyHelper/KirbySpawnPoint"] = {
            placements = {
                default = "Kirby Spawn Point"
            },
            attributes = {
                spawnAsKirby = "Spawn as Kirby",
                startingAbility = "Starting Ability"
            }
        },
        ["MaggyHelper/AbilityStar"] = {
            placements = {
                fire = "Ability Star (Fire)",
                ice = "Ability Star (Ice)",
                sword = "Ability Star (Sword)",
                beam = "Ability Star (Beam)",
                spark = "Ability Star (Spark)",
                stone = "Ability Star (Stone)",
                bomb = "Ability Star (Bomb)",
                hammer = "Ability Star (Hammer)",
                ninja = "Ability Star (Ninja)",
                cutter = "Ability Star (Cutter)"
            },
            attributes = {
                ability = "Copy Ability Type"
            }
        },
        ["MaggyHelper/KirbyBoss"] = {
            placements = {
                default = "Shadow Kirby Boss"
            },
            attributes = {
                health = "Boss Health",
                attackCooldown = "Attack Cooldown",
                bossMusic = "Boss Music Event"
            }
        },
        ["MaggyHelper/DededeBoss"] = {
            placements = {
                default = "King Dedede Boss"
            },
            attributes = {
                health = "Boss Health",
                attackCooldown = "Attack Cooldown",
                bossMusic = "Boss Music Event"
            }
        },
        ["MaggyHelper/MetaKnightBoss"] = {
            placements = {
                default = "Meta Knight Boss"
            },
            attributes = {
                health = "Boss Health",
                attackCooldown = "Attack Cooldown",
                bossMusic = "Boss Music Event"
            }
        },
        ["MaggyHelper/WaddleDee"] = {
            placements = {
                default = "Waddle Dee"
            },
            attributes = {
                health = "Health",
                moveSpeed = "Move Speed",
                patrolDistance = "Patrol Distance",
                canBeInhaled = "Can Be Inhaled"
            }
        },
        ["MaggyHelper/WaddleDoo"] = {
            placements = {
                default = "Waddle Doo"
            },
            attributes = {
                health = "Health",
                moveSpeed = "Move Speed",
                attackCooldown = "Attack Cooldown",
                canBeInhaled = "Can Be Inhaled"
            }
        },
        ["MaggyHelper/Gordo"] = {
            placements = {
                stationary = "Gordo (Stationary)",
                horizontal = "Gordo (Horizontal)",
                vertical = "Gordo (Vertical)",
                diagonal = "Gordo (Diagonal)",
                circular = "Gordo (Circular)"
            },
            attributes = {
                movementType = "Movement Type",
                moveDistance = "Move Distance",
                moveSpeed = "Move Speed",
                pauseDuration = "Pause Duration"
            }
        },
        ["MaggyHelper/ScarfyEnemy"] = {
            placements = {
                default = "Scarfy"
            },
            attributes = {
                health = "Health",
                moveSpeed = "Move Speed",
                chaseSpeed = "Chase Speed",
                canBeInhaled = "Can Be Inhaled"
            }
        }
    },
    
    -- Trigger names
    triggers = {
        ["MaggyHelper/BossFightTrigger"] = {
            placements = {
                default = "Boss Fight Trigger"
            },
            attributes = {
                bossType = "Boss Type",
                lockRoom = "Lock Room",
                playMusic = "Play Boss Music",
                bossMusic = "Boss Music Event"
            }
        },
        ["MaggyHelper/KirbyAbilityTrigger"] = {
            placements = {
                give_ability = "Kirby Ability (Give)",
                remove_ability = "Kirby Ability (Remove)",
                toggle_float = "Kirby Ability (Toggle Float)",
                toggle_inhale = "Kirby Ability (Toggle Inhale)"
            },
            attributes = {
                action = "Action",
                ability = "Ability",
                onlyOnce = "Only Once"
            }
        },
        ["MaggyHelper/EnemySpawnTrigger"] = {
            placements = {
                waddle_dee = "Enemy Spawn (Waddle Dee)",
                waddle_doo = "Enemy Spawn (Waddle Doo)",
                gordo = "Enemy Spawn (Gordo)",
                scarfy = "Enemy Spawn (Scarfy)"
            },
            attributes = {
                enemyType = "Enemy Type",
                count = "Spawn Count",
                spawnDelay = "Spawn Delay",
                respawn = "Respawn on Death"
            }
        }
    }
}
